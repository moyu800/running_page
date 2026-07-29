"""佳明 CN → Global 同步 — 从中国区下载, 上传到国际区, 再落库。

替代旧 garmin_sync_cn_global.py。修复:
  - global 账号 domain 不再硬编码 "COM"(旧代码 # FIXME): 由 --global-is-cn 决定。
  - 上传前经 fit_adaptor 处理(伪造设备信息, 让 Global 识别非 Garmin 来源的 fit)。

用法:
  python -m backend.sync_garmin.cn_to_global <cn_secret> <global_secret> [--only-run] [--global-is-cn]
"""

import argparse
import os
import sys

from backend.config import FIT_FOLDER, GPX_FOLDER, JSON_FILE, SQL_FILE
from backend.sync_garmin.auth import GarminClient
from backend.sync_garmin.downloader import download_new_activities
from backend.sync_garmin.fit_adaptor import process_garmin_data
from backend.sync_garmin.sync import get_downloaded_ids
from backend.utils import make_activities_file


def _collect_upload_files(new_ids):
    """收集待上传文件: 优先 fit, 回退到手动上传的 gpx。"""
    files = []
    for activity_id in new_ids:
        fit_path = os.path.join(FIT_FOLDER, f"{activity_id}.fit")
        gpx_path = os.path.join(GPX_FOLDER, f"{activity_id}.gpx")
        if os.path.exists(fit_path):
            files.append(fit_path)
        elif os.path.exists(gpx_path):
            files.append(gpx_path)
    return files


def _upload_to_global(global_client, files, use_fake_garmin_device=True):
    """把文件逐个处理后上传到 Global。失败记录不中断。"""
    failed = []
    for file_path in files:
        try:
            with open(file_path, "rb") as f:
                processed = process_garmin_data(f, use_fake_garmin_device)
            # 处理后的 bytes 写临时文件供 upload_activity 读
            tmp_path = file_path + ".upload"
            with open(tmp_path, "wb") as f:
                f.write(processed.read())
            try:
                global_client.upload(tmp_path)
                print(f"上传成功: {os.path.basename(file_path)}")
            finally:
                os.remove(tmp_path)
        except Exception as e:
            failed.append((file_path, str(e)))
            print(f"上传失败 {os.path.basename(file_path)}: {e}")
    return failed


def run_cn_to_global(cn_secret, global_secret, is_only_running, global_is_cn):
    for folder in (FIT_FOLDER, GPX_FOLDER):
        if not os.path.exists(folder):
            os.makedirs(folder)

    downloaded = list(
        set(get_downloaded_ids(FIT_FOLDER) + get_downloaded_ids(GPX_FOLDER))
    )

    # Step 1: 从 CN 下载新活动(fit)
    cn_client = GarminClient.from_token(
        cn_secret, is_cn=True, is_only_running=is_only_running
    )
    new_ids, id2title = download_new_activities(
        cn_client, downloaded, FIT_FOLDER, "fit"
    )

    # Step 2: 上传到 Global(domain 参数化, 不再硬编码 COM)
    to_upload = _collect_upload_files(new_ids)
    print(f"待上传 Global 的文件: {len(to_upload)} 个")
    if to_upload:
        global_client = GarminClient.from_token(
            global_secret, is_cn=global_is_cn, is_only_running=is_only_running
        )
        _upload_to_global(global_client, to_upload)

    # Step 3: 落库(gpx + fit)
    make_activities_file(
        SQL_FILE, GPX_FOLDER, JSON_FILE, file_suffix="gpx", activity_title_dict=id2title
    )
    make_activities_file(
        SQL_FILE, FIT_FOLDER, JSON_FILE, file_suffix="fit", activity_title_dict=id2title
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("cn_secret_string", nargs="?", help="CN token from make_secret")
    parser.add_argument(
        "global_secret_string", nargs="?", help="Global token from make_secret"
    )
    parser.add_argument(
        "--only-run",
        dest="only_run",
        action="store_true",
        help="if is only for running",
    )
    parser.add_argument(
        "--global-is-cn",
        dest="global_is_cn",
        action="store_true",
        help="if the global(target) account is also on garmin.cn domain",
    )
    options = parser.parse_args()
    if not options.cn_secret_string or not options.global_secret_string:
        print("Missing cn_secret_string or global_secret_string")
        sys.exit(1)
    run_cn_to_global(
        options.cn_secret_string,
        options.global_secret_string,
        options.only_run,
        options.global_is_cn,
    )


if __name__ == "__main__":
    main()
