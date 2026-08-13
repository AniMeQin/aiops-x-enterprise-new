# ADR 0002: 将 Kali 测试机用于开发验收

- 状态：已接受
- 日期：2026-08-12

## 背景

项目原定的开发和测试主机基线为 Ubuntu 22.04 LTS，本轮实际授权的设备是 `10.1.12.96`，运行 Kali GNU/Linux Rolling 2026.3。该主机已运行 Greenbone/OpenVAS、PostgreSQL 18 和 Mosquitto，不能覆盖或复用其数据和端口。

## 决策

- 仅将该 Kali 主机用于授权的开发验收，不将其定义为生产基线。
- 使用 Docker Compose 隔离 AIOps-X 的 PostgreSQL/pgvector、Redis、NATS 和 MinIO，不连接宿主机已有 PostgreSQL 或 Redis。
- 仅将 Web 入口 `8080/tcp` 绑定到局域网；API、AI、NATS 监控和 MinIO 控制台保持回环地址或 Compose 内网可见。
- 使用独立 release 目录、共享环境文件和 Docker 命名卷；发布前保留旧 release，以 `current` 软链接切换，不删除持久化数据。
- 容器设置内存上限，避免影响宿主机现有安全扫描服务。

## 后果

Kali Rolling 与 Ubuntu 22.04 在宿主内核、systemd 和软件包生命周期上不同，因此本环境的通过不替代 Ubuntu 22.04 和生产 Kubernetes 验收。应用层依赖由容器锁定，但仍需在正式目标系统重复容灾、安全基线和性能测试。
