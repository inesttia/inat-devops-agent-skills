---
name: iac-change-cost-preview
description: Previews the monthly cost of a CloudFormation change in this repository before it is deployed. Use whenever a template under cloudformation/ is added or edited, when the user asks what a template change will add or cost per month, or when reviewing a branch or pull request that touches CloudFormation, SAM, or CDK-synthesized templates. Runs scripts/cost_preview.py, which diffs the template against a git base, extracts sizing for every fixed-cost resource, prices it live with the AWS Price List API for the target Region, and prints one Markdown table with a monthly total. Never hardcodes a rate; usage-based charges are named, not estimated.
---
# IaC Change Cost Preview (Kiro)

This is the Kiro-side companion of the AWS DevOps Agent skill of the same name. The method is identical; the execution is a script so the result is deterministic and takes seconds.

## When to run

- A file matching `cloudformation/**/*.yaml|yml|json` was created or edited in this session (the `iac-cost-preview-on-save` hook fires this skill for agent edits; for your own edits, type `/iac-change-cost-preview`).
- The user asks what a template or branch will add to the account or what it will cost per month.
- Before a commit or pull request that touches a template.

## Procedure

1. **Resolve inputs** from `cloudformation/README.md`: stack name, account, target Region, and pipeline parameter values for the template. If the Region is missing there and the user has not given it, ask; never default to us-east-1.
2. **Pick the base.** For "what does my change add", compare the working tree against the last commit on the base branch: `--base origin/main` (or `main`). For "what does this PR add", use the PR's base branch. If the template does not exist at the base, every resource is an Add and the report says so.
3. **Run the script** from the repository root:

   ```bash
   python3 .kiro/skills/iac-change-cost-preview/scripts/cost_preview.py \
     --template cloudformation/<file>.yaml --base origin/main \
     --region <REGION> --stack <STACK> --account <ACCOUNT_ID> \
     [--profile <aws-profile>] [--param Key=Value ...] [--verbose]
   ```

   `--profile` selects the AWS credentials used for `pricing:GetProducts`. The Price List API endpoint is always us-east-1; the `--region` value is the Region the stack deploys to and only affects which rates are looked up.
4. **Read the mode line.** `Mode: full` means every row was priced live on this run. `Mode: worksheet` means the Price List API was not reachable (no or expired credentials); the table shows `pending` and a JSON worksheet follows. In that case tell the user which credentials to refresh (`aws sts get-caller-identity --profile <p>` must succeed) and offer to re-run. Do not fill in numbers yourself.
5. **Present the table as the script printed it.** Do not round, reorder, or add figures. You may add one or two sentences above it: the largest row, and anything the user should decide (an unpriced row, an assumption they can correct with `--param`).
6. **Explain `not priced` rows** using `references/pricing-reference.md`: it lists, per resource type, the Price List filters the script uses. `0 products` usually means a filter value differs for that Region or service; `ambiguous` means several products matched and the script refused to pick one. Suggest the fix (a `--param`, or a filter correction in the script) rather than guessing a rate.

## Rules

- **Live rate rule.** Every dollar figure comes from `pricing:GetProducts` on this run. Never type a rate from memory or from a pricing page, and never edit the script's output to add one.
- **Fixed versus usage-based.** The total covers fixed charges only. Usage-based rows (S3, Lambda, SQS, SNS, log groups, on-demand DynamoDB) show `usage-based`; estimate them only if the user gives a volume, and say so next to the figure.
- **Never `$0.00` for an unknown.** A lookup that failed is `not priced`; a lookup that was not attempted is `pending`.
- **Static diff.** The script classifies Add, Modify, and Remove by logical ID and property changes. It does not evaluate Conditions, `Fn::If`, Transforms, or Replacement. Say so when a template uses them.
- **Read-only.** The script calls only the Price List API. It never creates a change set, never deploys, and never modifies the account.

## Files

- `scripts/cost_preview.py` — the whole method as code; `--help` lists the options.
- `references/pricing-reference.md` — per resource type: Price List `ServiceCode`, filter fields and values, Region scoping (`regionCode` filter or usagetype prefix), unit, formula, and the billing-model claims the formula depends on.
