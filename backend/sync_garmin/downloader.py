"""佳明活动下载层 — 列活动、并发下载、FIT 解压、gpx summary 注入。

相比旧 garmin_sync.py 的修复:
  - 列活动: 递归分页 → while 迭代(不再有爆栈风险)
  - 下载失败: except:continue 静默吞 → 记录 id+原因, 结尾汇总
  - FIT 解压: 依赖 {id}_ACTIVITY.fit 命名 → 按 zip 内实际 .fit 内容定位
  - 并发: 新库同步调用, 用线程池替代旧 asyncio.gather
"""

import concurrent.futures
import datetime as dt
import os
import zipfile
from io import BytesIO

from lxml import etree

PAGE_SIZE = 100
DOWNLOAD_CONCURRENCY = 10

# gpx summary 注入的字段(与旧 add_summary_info 一致)
SUMMARY_FIELDS = [
    "distance",
    "average_hr",
    "average_speed",
    "start_time",
    "end_time",
    "moving_time",
    "elapsed_time",
]


def list_all_activity_ids(client):
    """迭代分页拉全部活动 id。空页即停,不再递归。"""
    ids = []
    start = 0
    while True:
        page = client.list_activities(start, PAGE_SIZE)
        if not page:
            break
        ids.extend(str(a.get("activityId", "")) for a in page)
        start += PAGE_SIZE
    return [i for i in ids if i]


def _extract_summary_infos(activity_summary):
    """从单条活动详情提取 summary 字段。结构缺失时返回空 dict(降级不崩)。"""
    infos = {}
    summary_dto = (activity_summary or {}).get("summaryDTO")
    if not summary_dto:
        return infos
    try:
        infos["distance"] = summary_dto.get("distance")
        infos["average_hr"] = summary_dto.get("averageHR")
        infos["average_speed"] = summary_dto.get("averageSpeed")
        start_gmt = summary_dto.get("startTimeGMT")
        if start_gmt:
            start_time = dt.datetime.fromisoformat(start_gmt[:-1] + "+00:00")
            duration = summary_dto.get("duration") or 0
            infos["start_time"] = start_time.isoformat()
            infos["end_time"] = (
                start_time + dt.timedelta(seconds=duration)
            ).isoformat()
        infos["moving_time"] = summary_dto.get("movingDuration")
        infos["elapsed_time"] = summary_dto.get("elapsedDuration")
    except Exception as e:
        print(f"  提取 summary 字段失败: {e}")
    return infos


def _inject_gpx_summary(gpx_bytes, summary_infos):
    """把 summary 字段注入 gpx 的 <extensions> 节点(track_loader 会读)。"""
    if not summary_infos:
        return gpx_bytes
    try:
        root = etree.fromstring(gpx_bytes)
        ext = etree.Element("extensions")
        ext.text = ext.tail = "\n"
        for field in SUMMARY_FIELDS:
            elem = etree.SubElement(ext, field)
            value = summary_infos.get(field)
            elem.text = "" if value is None else str(value)
            elem.tail = "\n"
        root.insert(0, ext)
        return etree.tostring(root, encoding="utf-8", pretty_print=True)
    except etree.XMLSyntaxError as e:
        print(f"  gpx 解析失败, 跳过 summary 注入: {e}")
    except Exception as e:
        print(f"  summary 注入失败: {e}")
    return gpx_bytes


def _save_fit(zip_bytes, activity_id, folder):
    """fit 端点返回 zip, 解压出真正的 .fit。按内容定位, 不依赖 _ACTIVITY.fit 命名。"""
    with zipfile.ZipFile(BytesIO(zip_bytes)) as zf:
        fit_names = [n for n in zf.namelist() if n.lower().endswith(".fit")]
        if not fit_names:
            raise ValueError(f"zip 内无 .fit 文件: {zf.namelist()}")
        target = os.path.join(folder, f"{activity_id}.fit")
        with zf.open(fit_names[0]) as src, open(target, "wb") as dst:
            dst.write(src.read())
    return target


def _download_one(client, activity_id, file_type, folder, summary_infos_map):
    """下载单条活动并写盘。异常向上抛(由调用方带 id 记录)。"""
    data = client.download(activity_id, file_type)
    if file_type == "fit":
        _save_fit(data, activity_id, folder)
        return
    if file_type == "gpx":
        data = _inject_gpx_summary(data, summary_infos_map.get(activity_id))
    file_path = os.path.join(folder, f"{activity_id}.{file_type}")
    with open(file_path, "wb") as fb:
        fb.write(data)


def download_new_activities(client, downloaded_ids, folder, file_type):
    """下载所有未下载的活动。返回 (新增 id 列表, id->标题 映射)。"""
    all_ids = list_all_activity_ids(client)
    to_download = [i for i in all_ids if i not in set(downloaded_ids)]
    print(f"{len(to_download)} new activities to be downloaded")

    id2title = {}
    summary_infos_map = {}
    for activity_id in to_download:
        try:
            summary = client.get_activity_summary(activity_id)
            id2title[activity_id] = summary.get("activityName", "")
            summary_infos_map[activity_id] = _extract_summary_infos(summary)
        except Exception as e:
            print(f"  获取活动摘要失败 {activity_id}: {e}")

    failed = []
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=DOWNLOAD_CONCURRENCY
    ) as pool:
        futures = {
            pool.submit(
                _download_one,
                client,
                activity_id,
                file_type,
                folder,
                summary_infos_map,
            ): activity_id
            for activity_id in to_download
        }
        for future in concurrent.futures.as_completed(futures):
            activity_id = futures[future]
            try:
                future.result()
            except Exception as e:
                failed.append((activity_id, str(e)))

    if failed:
        print(f"\n{len(failed)} 个活动下载失败(可重试):")
        for activity_id, reason in failed:
            print(f"  {activity_id}: {reason}")

    downloaded = [i for i in to_download if i not in {f[0] for f in failed}]
    return downloaded, id2title
