"""FIT 文件适配 — 修复心率缺失点, 可选注入伪造 Garmin 设备信息。

用途: CN→Global 上传时, Garmin 用设备信息识别活动来源;
非 Garmin 设备(如 WorkoutDoors)导出的 fit 需伪造设备信息才被 Global 接受。

use_fake_garmin_device 默认关闭, 仅 cn_to_global 显式开启。
fit_tool 不可用时显式警告并原样返回(旧代码是静默降级)。
"""

import traceback
from io import BytesIO

try:
    from fit_tool.fit_file import FitFile
    from fit_tool.fit_file_builder import FitFileBuilder
    from fit_tool.profile.messages.device_info_message import DeviceInfoMessage
    from fit_tool.profile.messages.record_message import RecordMessage

    FIT_TOOL_AVAILABLE = True
except ImportError:
    FIT_TOOL_AVAILABLE = False

# 设备参数来源: https://github.com/garmin/fit-python-sdk
MANUFACTURER_GARMIN = 1
GARMIN_DEVICE_PRODUCT_ID = 3415  # Forerunner 245
GARMIN_SOFTWARE_VERSION = 3.58
# 序列号必须是真实的, Garmin 才会识别为 Forerunner 245
GARMIN_DEVICE_SERIAL_NUMBER = 1234567890

_INVALID_HR = 255


def is_fit_file(file):
    file.seek(8)
    header = file.read(4)
    file.seek(0)
    return header == b".FIT"


def process_garmin_data(origin_file, use_fake_garmin_device=False):
    """处理 fit 文件。非 fit 或 fit_tool 不可用时原样返回。"""
    if not FIT_TOOL_AVAILABLE:
        print(
            "[warn] fit-tool 未安装, 跳过 FIT 处理(心率修复/设备注入不生效)。"
            "Python < 3.13 可装 fit-tool 启用此功能。"
        )
        origin_file.seek(0)
        return BytesIO(origin_file.read())

    try:
        content = origin_file.read()
        if not is_fit_file(origin_file):
            return BytesIO(content)
        return _do_process(content, use_fake_garmin_device)
    except Exception:
        print("[warn] FIT 处理失败, 使用原始文件")
        traceback.print_exc()
        origin_file.seek(0)
        return BytesIO(origin_file.read())


def _do_process(file_content, use_fake_garmin_device):
    """修复心率数据, 按需注入伪造设备信息。"""
    fit_file = FitFile.from_bytes(file_content)
    builder = FitFileBuilder(auto_define=True)

    record_messages = []
    for record in fit_file.records:
        message = record.message
        if use_fake_garmin_device and message.global_id == DeviceInfoMessage.ID:
            continue  # 丢弃原设备信息(如 WorkoutDoors)
        elif not isinstance(message, RecordMessage):
            builder.add(message)
        else:
            record_messages.append(message)

    if use_fake_garmin_device:
        builder.add(_fake_device_info())

    for message in _fix_heart_rate(record_messages):
        builder.add(message)

    print("FIT 处理完成")
    return builder.build().to_bytes()


def _find_valid_hr(messages, current_index):
    """找最近的有效心率值(向后优先, 再向前)。"""
    for msg in messages[current_index + 1 :]:
        if msg.heart_rate is not None and msg.heart_rate != _INVALID_HR:
            return msg.heart_rate
    for msg in reversed(messages[:current_index]):
        if msg.heart_rate is not None and msg.heart_rate != _INVALID_HR:
            return msg.heart_rate
    return None


def _new_record_with_hr(old_message, heart_rate):
    new_message = RecordMessage()
    for field in old_message.fields:
        name = field.name
        if not hasattr(old_message, name):
            continue
        if name == "heart_rate":
            setattr(new_message, name, heart_rate)
        elif getattr(old_message, name) is not None:
            setattr(new_message, name, getattr(old_message, name))
    return new_message


def _fix_heart_rate(record_messages):
    """把 None/255 的心率替换为邻近有效值。"""
    result = []
    for i, message in enumerate(record_messages):
        if message.heart_rate is None or message.heart_rate == _INVALID_HR:
            valid = _find_valid_hr(record_messages, i)
            result.append(_new_record_with_hr(message, valid) if valid else message)
        else:
            result.append(message)
    print("心率数据修复完成")
    return result


def _fake_device_info():
    """构造伪造的 Garmin 设备信息消息。"""
    message = DeviceInfoMessage()
    message.serial_number = GARMIN_DEVICE_SERIAL_NUMBER
    message.manufacturer = MANUFACTURER_GARMIN
    message.garmin_product = GARMIN_DEVICE_PRODUCT_ID
    message.software_version = GARMIN_SOFTWARE_VERSION
    message.device_index = 0
    message.source_type = 5
    message.product = GARMIN_DEVICE_PRODUCT_ID
    print("注入 Garmin 设备信息完成")
    return message
