import os

# getting content root directory
current = os.path.dirname(os.path.realpath(__file__))  # backend/
parent = os.path.dirname(current)  # 项目根

# 下载落盘目录(运行时按需 makedirs)
GPX_FOLDER = os.path.join(parent, "GPX_OUT")
TCX_FOLDER = os.path.join(parent, "TCX_OUT")
FIT_FOLDER = os.path.join(parent, "FIT_OUT")
FOLDER_DICT = {
    "gpx": GPX_FOLDER,
    "tcx": TCX_FOLDER,
    "fit": FIT_FOLDER,
}

# 数据库随 backend 走(data.db 在 backend/ 内)
SQL_FILE = os.path.join(current, "data.db")
# 前端构建期消费的产物(必须落在 src/static/, parent=项目根)
JSON_FILE = os.path.join(parent, "src", "static", "activities.json")
# 已同步文件记录
SYNCED_FILE = os.path.join(parent, "imported.json")
