# CloudFormation stacks

Deployment configuration used by the pipeline. The `iac-change-cost-preview` skill reads this file to resolve the stack name, target Region, and parameters for a pull request (its Step 0).

| Template | Stack name | Target Region | Parameters |
|---|---|---|---|
| `payments-ledger.yaml` | `payments-ledger` | `eu-west-1` | `Environment=prod` |

The stack is not deployed yet; a preview of this template is a `CREATE` change set.
