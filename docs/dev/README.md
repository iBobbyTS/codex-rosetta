# Codex-Rosetta Developer Documentation

Developer documentation is maintained in English. User-facing documentation
lives in [`docs/en`](../en/README.md) and [`docs/zh-cn`](../zh-cn/README.md).

## Compatibility

- [Codex source compatibility](version-compatibility/README.md)
- [Compatibility points](version-compatibility/compatibility-points.md)
- [Upgrade checklist](version-compatibility/upgrade-checklist.md)
- [Upgrade reports](version-compatibility/reports/README.md)

## Architecture and research

- [Design history](design/architecture.md)
- [Provider and model parameter survey](provider_model_params/survey.md)
- [SDK and IR research](sdk_ir/)
- [Codex tool localization trace QA](codex-tool-localization/trace-qa.md)

## Manual development deployment

The manual development deployment path remains available:

```bash
make deploy-dev SSH_TARGET=cloud.usa2
```

`deploy-dev` builds from the current working tree rather than the committed
state. Pull the intended branch and verify that `src/` contains no unintended
changes before deploying. The command builds a development wheel and Docker
image, then sends it to the configured remote stack over SSH.
