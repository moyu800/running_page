"""佳明主同步 — 下载活动文件并落库生成 activities.json。

替代旧 garmin_sync.py。流程:
  认证(token/账密) → 迭代下载新活动 → make_activities_file 落库。

CLI 与旧脚本对齐(降低对照成本):
  python -m backend.sync_garmin.sync <secret> [--is-cn] [--only-run] [--tcx|--fit]

secret 是 make_secret.py 产出的 token 串。
"""

import argparse
import os
import sys

from backend.config import FOLDER_DICT, JSON_FILE, SQL_FILE
from backend.sync_garmin.auth import GarminClient
from backend.sync_garmin.downloader import download_new_activities
from backend.utils import make_activities_file


def get_downloaded_ids(folder):
    """已下载文件名(去扩展名)= 已同步 id。"""
    return [i.split(".")[0] for i in os.listdir(folder) if not i.startswith(".")]


def run_sync(secret, is_cn, is_only_running, file_type):
    folder = FOLDER_DICT.get(file_type, FOLDER_DICT["gpx"])
    if not os.path.exists(folder):
        os.makedirs(folder)

    downloaded_ids = get_downloaded_ids(folder)
    # fit 可能混入用户手动上传的 gpx, 两个目录的 id 都算已下载
    if file_type == "fit":
        gpx_folder = FOLDER_DICT["gpx"]
        if not os.path.exists(gpx_folder):
            os.makedirs(gpx_folder)
        downloaded_ids = list(set(downloaded_ids + get_downloaded_ids(gpx_folder)))

    client = GarminClient.from_token(
        secret, is_cn=is_cn, is_only_running=is_only_running
    )
    _, id2title = download_new_activities(client, downloaded_ids, folder, file_type)

    # fit 目录里可能有 gpx(手动上传), 先按 gpx 落一遍
    if file_type == "fit":
        make_activities_file(
            SQL_FILE,
            FOLDER_DICT["gpx"],
            JSON_FILE,
            file_suffix="gpx",
            activity_title_dict=id2title,
        )
    make_activities_file(
        SQL_FILE,
        folder,
        JSON_FILE,
        file_suffix=file_type,
        activity_title_dict=id2title,
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("secret_string", nargs="?", help="token from make_secret.py")
    parser.add_argument(
        "--is-cn", dest="is_cn", action="store_true", help="if garmin account is cn"
    )
    parser.add_argument(
        "--only-run",
        dest="only_run",
        action="store_true",
        help="if is only for running",
    )
    parser.add_argument(
        "--tcx",
        dest="download_file_type",
        action="store_const",
        const="tcx",
        default="gpx",
        help="download as tcx",
    )
    parser.add_argument(
        "--fit",
        dest="download_file_type",
        action="store_const",
        const="fit",
        default="gpx",
        help="download as fit",
    )
    options = parser.parse_args()
    if not options.secret_string:
        print("Missing secret_string argument")
        sys.exit(1)
    run_sync(
        options.secret_string,
        options.is_cn,
        options.only_run,
        options.download_file_type,
    )


if __name__ == "__main__":
    main()
