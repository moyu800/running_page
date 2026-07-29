"""生成佳明 token — 账密登录一次, 产出可复用的 token 串。

替代旧 get_garmin_secret.py(garth.login + garth.client.dumps)。
python-garminconnect 的 token 序列化在内层 client 上:
  client.client.dumps() -> {"di_token","di_refresh_token","di_client_id"} 的 JSON 串。
该串可被 sync 端 client.loads(串) 吃回, 存入 GITHUB secret 供 CI 复用。

用法:
  python -m backend.sync_garmin.make_secret <email> <password> [--is-cn]
"""

import argparse
import sys

from garminconnect import Garmin


def make_secret(email, password, is_cn=False):
    """账密登录并返回可复用的 token 串。"""
    client = Garmin(email=email, password=password, is_cn=is_cn)
    client.login()
    return client.client.dumps()


def main():
    parser = argparse.ArgumentParser(description="生成佳明 token")
    parser.add_argument("email", nargs="?", help="佳明账号邮箱")
    parser.add_argument("password", nargs="?", help="佳明账号密码")
    parser.add_argument("--is-cn", dest="is_cn", action="store_true", help="中国区账号")
    options = parser.parse_args()
    if not options.email or not options.password:
        print("缺少 email/password 参数")
        sys.exit(1)
    secret = make_secret(options.email, options.password, options.is_cn)
    print(secret)


if __name__ == "__main__":
    main()
