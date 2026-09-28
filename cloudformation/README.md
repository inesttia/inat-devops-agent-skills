# CloudFormation stacks

Deployment configuration used by the pipeline. The `iac-change-cost-preview` skill reads this file to resolve the stack name, target account, Region, and parameters for a pull request (its Step 0).

| Template | Stack name | Account | Target Region | Parameters |
|---|---|---|---|---|
| `payments-ledger.yaml` | `payments-ledger` | `<ACCOUNT_ID>` (fill in) | `eu-west-1` | `Environment=prod`, `DbInstanceClass=db.r6g.large`, `DbAllocatedStorageGb=200`, `WorkerInstanceType=m6g.large`, `WorkerDesiredCapacity=2`, `CacheNodeType=cache.r6g.large` (VPC and subnet parameters use template defaults) |

The stack is not deployed yet; a preview of this template is a `CREATE` change set.

> **Describe, don't execute.** Nothing in this repository deploys anything. Tools and agents reading these templates may create a CloudFormation change set to describe what a change would do; a change set must be deleted after it is described and must never be executed from a review or a preview.
