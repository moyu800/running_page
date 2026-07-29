
FROM python:3.12-slim AS develop-py
WORKDIR /root/running_page
COPY ./requirements.txt /root/running_page/requirements.txt
RUN sed -i 's@http://archive.ubuntu.com/ubuntu/@https://mirrors.tuna.tsinghua.edu.cn/ubuntu/@g' /etc/apt/sources.list \
  && sed -i 's@http://security.ubuntu.com/ubuntu/@https://mirrors.tuna.tsinghua.edu.cn/ubuntu/@g' /etc/apt/sources.list \
  && apt-get update \
  && apt-get install -y --no-install-recommends git \
  && apt-get purge -y --auto-remove \
  && rm -rf /var/lib/apt/lists/* \
  && pip3 install -i https://mirrors.aliyun.com/pypi/simple/ pip -U \
  && pip3 config set global.index-url https://mirrors.aliyun.com/pypi/simple/ \
  && pip3 install -r requirements.txt

FROM node:18  AS develop-node
WORKDIR /root/running_page
COPY ./package.json /root/running_page/package.json
COPY ./pnpm-lock.yaml /root/running_page/pnpm-lock.yaml
RUN npm config set registry https://registry.npmmirror.com \
  && corepack enable \
  && COREPACK_NPM_REGISTRY=https://registry.npmmirror.com pnpm install

FROM develop-py AS data
ARG secret_string

WORKDIR /root/running_page
COPY . /root/running_page/
ARG DUMMY=unknown
# 佳明中国区同步(secret 由 backend.sync_garmin.make_secret 生成)
RUN DUMMY=${DUMMY}; \
  python3 -m backend.sync_garmin.sync ${secret_string} --is-cn


FROM develop-node AS frontend-build
WORKDIR /root/running_page
COPY --from=data /root/running_page /root/running_page
RUN pnpm run build

FROM nginx:alpine AS web
COPY --from=frontend-build /root/running_page/dist /usr/share/nginx/html/
COPY --from=frontend-build /root/running_page/assets /usr/share/nginx/html/assets
COPY nginx.conf /etc/nginx/conf.d/default.conf
