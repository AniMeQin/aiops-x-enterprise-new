# AIOps-X Helm Chart

该 Chart 面向生产控制平面，外部依赖由平台团队提供。发布前必须把所有镜像都替换为经扫描、签名并带 SBOM 的 `sha256` digest，同时创建 `existingSecret`。默认不在 values 中保存任何凭据。Secret 除环境变量键外还必须包含 `vault-token` 与六个 Agent PKI 文件；生产推荐由 Vault Agent/External Secrets 和企业 PKI 自动投递、轮换这些键。

```bash
helm lint deploy/helm/aiops-x --set productionEnforced=false
helm template aiops-x deploy/helm/aiops-x --set productionEnforced=false
```

生产环境保持 `productionEnforced=true`，配置 TLS Ingress、OIDC/Vault、非空的依赖出口 CIDR、Pod Security Admission 及独立的 API/Worker/AI 身份。生产门禁会拒绝无 digest 的镜像、空依赖 CIDR、关闭 Web Ingress 或关闭独立 mTLS Agent Gateway 的发布。数据库迁移使用单独的 Helm hook Job；应用 Pod 不自动执行迁移。

若启用 `externalSecrets`，首次安装前必须先让 External Secrets Operator 同步出 `existingSecrets` 中声明的目标 Secret，再执行 Helm 安装。这样 pre-install 数据库迁移 Job 不会在 Secret 尚未生成时启动；升级时也不会让正在运行的工作负载短暂失去 Secret。
