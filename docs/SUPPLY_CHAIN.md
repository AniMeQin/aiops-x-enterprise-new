# 镜像供应链门禁

生产镜像由 `.github/workflows/supply-chain.yml` 构建并直接推送不可变 digest。流水线生成 BuildKit provenance 与 CycloneDX SBOM，Trivy 对未修复的高危/严重漏洞执行阻断，然后通过 GitHub OIDC 的 Sigstore 身份对镜像和 SBOM attestation 签名。

Helm 的 `productionEnforced=true` 会拒绝 tag 或空 digest。发布人员必须先运行 `scripts/supply-chain/verify-image.sh` 校验签名身份、SBOM attestation 与漏洞门禁，再将确切 digest 写入受审阅的环境 values。禁止把私有 Cosign 密钥、Registry Token 或扫描豁免提交到仓库。
