# 固定依赖制品

`pgvector-v0.8.0.tar.gz` 来自 pgvector 官方 GitHub 标签 `v0.8.0`（commit `2627c5ff775ae6d7aef0c430121ccf857842d2f2`）。

SHA-256：`867a2c328d4928a5a9d6f052cd3bc78c7d60228a9b914ad32aa3db88e9de27b0`

引入本地制品是为了使受限测试网络的 Docker 构建可重现。Dockerfile 在编译前必须重新校验该哈希。

`pgdg-archive-keyring.asc` 来自 PostgreSQL 官方 Debian 仓库，`pgdg-archive-keyring.gpg` 是由该公钥生成的二进制 keyring，仅用于验证构建阶段的 `postgresql-server-dev-16` 软件包。

- 指纹：`B97B0AFCAA1A47F044F244A07FCC7D46ACCC4CF8`
- SHA-256：`0144068502a1eddd2a0280ede10ef607d1ec592ce819940991203941564e8e76`
- 二进制 keyring SHA-256：`8ca1b2fb3a2533cc44b87ee146a03858f6e8ea31c1f165dfd38dc270c04ada0f`
