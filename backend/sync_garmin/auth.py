"""佳明认证封装 — 基于 python-garminconnect(garth 废弃后的继任库)。

把认证收敛成薄接口,隔离底层库的选择:
  - from_token: 用已导出的 token 串或 token 目录构造(日常同步走这条)
  - login_with_credentials: 账密登录,内部走 curl_cffi 绕 Cloudflare TLS 指纹

CN 区由 is_cn 开关控制,库内部切 garmin.cn,不再需要旧代码那种 ssl_verify=False 脏招。
"""

from garminconnect import Garmin

# file_type -> 库下载枚举
DOWNLOAD_FORMATS = {
    "gpx": Garmin.ActivityDownloadFormat.GPX,
}


class GarminClient:
    """python-garminconnect 的薄封装,只暴露同步所需的能力。"""

    def __init__(self, client: Garmin, is_only_running=False):
        self._client = client
        self.is_only_running = is_only_running

    @classmethod
    def from_token(cls, token, is_cn=False, is_only_running=False):
        """用已有 token 串构造。token 是 make_secret 产出的 dumps() JSON 串。

        直接走内层 client.loads(串): dumps() 产出的串很短(<512), 若走
        login(tokenstore=串) 会被库的 len>512 分支误判为文件路径而失败。
        """
        client = Garmin(is_cn=is_cn)
        client.client.loads(token)
        return cls(client, is_only_running)

    @classmethod
    def login_with_credentials(
        cls, email, password, is_cn=False, prompt_mfa=None, is_only_running=False
    ):
        """账密登录,返回可用于后续下载或产出 token 的实例。"""
        client = Garmin(
            email=email, password=password, is_cn=is_cn, prompt_mfa=prompt_mfa
        )
        client.login()
        return cls(client, is_only_running)

    def list_activities(self, start, limit):
        """拉一页活动摘要(原始 dict 列表)。"""
        activity_type = "running" if self.is_only_running else None
        return self._client.get_activities(start, limit, activity_type)

    def get_activity_summary(self, activity_id):
        """拉单条活动详情(用于 summary 注入与标题)。"""
        return self._client.get_activity(activity_id)

    def download(self, activity_id, file_type):
        """下载活动为指定格式,返回 bytes。"""
        dl_fmt = DOWNLOAD_FORMATS[file_type]
        return self._client.download_activity(activity_id, dl_fmt=dl_fmt)

    @property
    def raw(self):
        """暴露底层 Garmin 对象,应急用。"""
        return self._client
