# IaC Cost Lens

Shows the live monthly cost of every CloudFormation resource as a CodeLens above it, and the fixed monthly delta for the whole template in the status bar. Rates come from the AWS Price List API on every run via `.kiro/skills/iac-change-cost-preview/scripts/cost_preview.py`; nothing is hardcoded and usage-based resources are labelled, not estimated.

Build and install into Kiro:

```bash
cd tools/iac-cost-lens
npm install && npm run compile && npx @vscode/vsce package --no-dependencies
"/Applications/Kiro.app/Contents/Resources/app/bin/code" --install-extension iac-cost-lens-*.vsix --force
```

Requires `python3` with `boto3` and `PyYAML`, and AWS credentials that allow `pricing:GetProducts` (default credential chain, or set `iacCostLens.awsProfile`). Configure stack, account, Region and parameters per template in `cloudformation/cost-preview.json`.
