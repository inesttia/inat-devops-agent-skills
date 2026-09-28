#!/usr/bin/env python3
"""IaC change cost preview: diff a CloudFormation template against a git base,
extract the sizing of every fixed-cost resource, price it live with the AWS
Price List API, and print one Markdown table with a monthly total.

    python3 cost_preview.py --template cloudformation/payments-ledger.yaml \
        --base main --region eu-west-1 [--profile ro-personal] [--param K=V ...]

Rules (mirrors SKILL.md):
  * dollar figures come only from pricing:GetProducts on this run
  * usage-based resources are listed, never estimated
  * an unresolved lookup prints `not priced`, never $0.00
  * without AWS credentials the script prints the same table with `pending`
    and a pricing worksheet (worksheet mode)
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys
from typing import Any

import yaml

HOURS = 730

# ------------------------------------------------------------------ yaml ----
class Tag:
    """Opaque CloudFormation intrinsic (!Ref, !Sub, !GetAtt, ...)."""

    def __init__(self, tag: str, value: Any):
        self.tag, self.value = tag, value

    def __repr__(self) -> str:  # stable for property diffs
        return f"{self.tag}({json.dumps(self.value, default=repr, sort_keys=True)})"


class CfnLoader(yaml.SafeLoader):
    pass


def _tag(loader: yaml.Loader, node: yaml.Node) -> Tag:
    if isinstance(node, yaml.ScalarNode):
        v: Any = loader.construct_scalar(node)
    elif isinstance(node, yaml.SequenceNode):
        v = loader.construct_sequence(node)
    else:
        v = loader.construct_mapping(node)
    return Tag(node.tag, v)


for _t in ("!Ref", "!Sub", "!GetAtt", "!If", "!Equals", "!Join", "!Select", "!Split",
           "!FindInMap", "!Not", "!And", "!Or", "!Condition", "!Base64", "!Cidr",
           "!ImportValue", "!GetAZs", "!Transform"):
    CfnLoader.add_constructor(_t, _tag)


def load_template(text: str) -> dict:
    if not text.strip():
        return {"Resources": {}, "Parameters": {}}
    if text.lstrip().startswith("{"):
        return json.loads(text)
    return yaml.load(text, Loader=CfnLoader) or {"Resources": {}}


def git_show(ref: str, path: str) -> str:
    try:
        return subprocess.run(["git", "show", f"{ref}:{path}"], check=True,
                              capture_output=True, text=True).stdout
    except subprocess.CalledProcessError:
        return ""  # file does not exist at base → everything is an Add


# ------------------------------------------------------------- resolve -----
def resolve(v: Any, params: dict, resources: dict, depth: int = 0) -> Any:
    """Resolve Ref/If/Select against parameter values; leave the rest alone."""
    if depth > 8:
        return v
    if isinstance(v, Tag):
        if v.tag == "!Ref" and v.value in params:
            return params[v.value]
        if v.tag == "!Ref" and v.value in resources:
            return v  # reference to another resource (handled by callers)
        if v.tag == "!If" and isinstance(v.value, list) and len(v.value) == 3:
            return resolve(v.value[1], params, resources, depth + 1)  # optimistic: true branch
        if v.tag == "!Select" and isinstance(v.value, list) and len(v.value) == 2:
            idx, lst = v.value
            lst = resolve(lst, params, resources, depth + 1)
            if isinstance(lst, list) and str(idx).isdigit() and int(idx) < len(lst):
                return lst[int(idx)]
        return v
    if isinstance(v, dict) and len(v) == 1:
        (k, inner), = v.items()
        if k == "Ref":
            return resolve(Tag("!Ref", inner), params, resources, depth + 1)
        if k.startswith("Fn::"):
            return resolve(Tag("!" + k[4:], inner), params, resources, depth + 1)
    return v


def param_values(tpl: dict, overrides: dict) -> dict:
    out = {}
    for name, spec in (tpl.get("Parameters") or {}).items():
        if name in overrides:
            val: Any = overrides[name]
        elif "Default" in spec:
            val = spec["Default"]
        else:
            continue
        if spec.get("Type") == "CommaDelimitedList" and isinstance(val, str):
            val = [x.strip() for x in val.split(",")]
        out[name] = val
    return out


def ref_target(v: Any) -> str | None:
    if isinstance(v, Tag) and v.tag == "!Ref" and isinstance(v.value, str):
        return v.value
    if isinstance(v, Tag) and v.tag == "!GetAtt":
        return v.value.split(".")[0] if isinstance(v.value, str) else v.value[0]
    return None


# ---------------------------------------------------------- pricing map -----
PREFIX = {
    "us-east-1": "", "us-east-2": "USE2", "us-west-1": "USW1", "us-west-2": "USW2",
    "eu-west-1": "EU", "eu-west-2": "EUW2", "eu-west-3": "EUW3", "eu-central-1": "EUC1",
    "eu-central-2": "EUC2", "eu-north-1": "EUN1", "eu-south-1": "EUS1", "eu-south-2": "EUS2",
    "ap-southeast-1": "APS1", "ap-southeast-2": "APS2", "ap-southeast-3": "APS4",
    "ap-southeast-4": "APS6", "ap-southeast-5": "APS7", "ap-southeast-6": "APS8",
    "ap-southeast-7": "APS9", "ap-northeast-1": "APN1", "ap-northeast-2": "APN2",
    "ap-northeast-3": "APN3", "ap-south-1": "APS3", "ap-south-2": "APS5", "ap-east-1": "APE1",
    "ap-east-2": "APE2", "sa-east-1": "SAE1", "ca-central-1": "CAN1", "ca-west-1": "CAN2",
    "me-south-1": "MES1", "me-central-1": "MEC1", "mx-central-1": "MXC1", "af-south-1": "AFS1",
    "il-central-1": "ILC1",
}
RDS_ENGINE = {"mysql": "MySQL", "postgres": "PostgreSQL", "mariadb": "MariaDB",
              "aurora-mysql": "Aurora MySQL", "aurora-postgresql": "Aurora PostgreSQL",
              "oracle-se2": "Oracle", "oracle-ee": "Oracle", "sqlserver-ex": "SQL Server",
              "sqlserver-web": "SQL Server", "sqlserver-se": "SQL Server", "sqlserver-ee": "SQL Server"}
RDS_VOLUME = {"gp3": "General Purpose-GP3", "gp2": "General Purpose (SSD)",
              "io1": "Provisioned IOPS (SSD)", "io2": "Provisioned IOPS (SSD)", "standard": "Magnetic"}
CACHE_ENGINE = {"redis": "Redis", "valkey": "Valkey", "memcached": "Memcached"}
USAGE_BASED = {
    "AWS::Lambda::Function": "requests + GB-seconds", "AWS::S3::Bucket": "storage GB-Mo + requests",
    "AWS::SQS::Queue": "requests", "AWS::SNS::Topic": "requests + notifications",
    "AWS::ApiGateway::RestApi": "requests", "AWS::ApiGatewayV2::Api": "requests",
    "AWS::Logs::LogGroup": "GB ingested + GB-Mo stored", "AWS::Events::Rule": "events",
    "AWS::Scheduler::Schedule": "invocations", "AWS::StepFunctions::StateMachine": "state transitions",
    "AWS::CloudFront::Distribution": "data transfer + requests", "AWS::Kinesis::Stream": "data in/out",
    "AWS::DynamoDB::Table(PAY_PER_REQUEST)": "read/write request units + storage",
    "AWS::ElastiCache::ServerlessCache": "GB-hours + ECPU", "AWS::EFS::FileSystem": "GB-Mo stored",
    "AWS::Route53::RecordSet": "queries", "AWS::SecretsManager::RotationSchedule": "Lambda invocations",
}


def up(region: str, value: str) -> str:
    p = PREFIX.get(region)
    if p is None:
        raise SystemExit(f"unknown region {region}")
    return f"{p}-{value}" if p else value


class Dim:
    """One price dimension for one resource."""

    def __init__(self, row: str, rtype: str, sizing: str, service: str, filters: dict,
                 unit_hint: str, qty: float, hourly: bool):
        self.row, self.rtype, self.sizing = row, rtype, sizing
        self.service, self.filters, self.unit_hint = service, filters, unit_hint
        self.qty, self.hourly = qty, hourly
        self.rate: float | None = None
        self.unit = unit_hint
        self.status = "pending"        # priced | not priced | pending | ambiguous
        self.note = ""

    def key(self) -> str:
        return json.dumps([self.service, self.filters], sort_keys=True)

    def monthly(self) -> float | None:
        if self.rate is None:
            return None
        return self.rate * self.qty * (HOURS if self.hourly else 1)


# --------------------------------------------------------- extractors -----
def ebs_dims(row: str, rtype: str, mappings: list, region: str, count: int, R) -> list[Dim]:
    out = []
    for i, m in enumerate(mappings or []):
        ebs = R(m.get("Ebs") or {})
        if not isinstance(ebs, dict) or "VolumeSize" not in ebs:
            continue
        vt = str(R(ebs.get("VolumeType", "gp3")))
        size = float(R(ebs["VolumeSize"]))
        out.append(Dim(f"{row} · volume {i + 1}", rtype, f"{int(size)} GiB {vt} × {count}", "AmazonEC2",
                       {"regionCode": region, "productFamily": "Storage", "volumeApiName": vt},
                       "GB-Mo", size * count, False))
        iops = R(ebs.get("Iops"))
        if vt == "gp3" and iops and float(iops) > 3000:
            out.append(Dim(f"{row} · volume {i + 1} IOPS", rtype, f"{int(float(iops)) - 3000} IOPS above baseline × {count}",
                           "AmazonEC2", {"regionCode": region, "productFamily": "System Operation", "volumeApiName": "gp3"},
                           "IOPS-Mo", (float(iops) - 3000) * count, False))
        if vt in ("io1", "io2") and iops:
            out.append(Dim(f"{row} · volume {i + 1} IOPS", rtype, f"{int(float(iops))} provisioned IOPS × {count}",
                           "AmazonEC2", {"regionCode": region, "productFamily": "System Operation", "volumeApiName": vt},
                           "IOPS-Mo", float(iops) * count, False))
    return out


def extract(lid: str, res: dict, resources: dict, params: dict, region: str):
    """Return (fixed_dims, usage_note, no_charge_reason)."""
    t = res.get("Type", "")
    P = res.get("Properties") or {}
    R = lambda v: resolve(v, params, resources)  # noqa: E731
    dims: list[Dim] = []

    if t == "AWS::EC2::Instance":
        it = str(R(P.get("InstanceType", "?")))
        ten = str(R(P.get("Tenancy", "default")))
        dims.append(Dim(lid, t, f"{it} · Linux (assumed) · {ten} tenancy", "AmazonEC2",
                        {"regionCode": region, "instanceType": it, "tenancy": "Shared" if ten == "default" else ten.capitalize(),
                         "operatingSystem": "Linux", "preInstalledSw": "NA", "capacitystatus": "Used",
                         "licenseModel": "No License required"}, "Hrs", 1, True))
        dims += ebs_dims(lid, t, R(P.get("BlockDeviceMappings")), region, 1, R)
        if R(P.get("AssociatePublicIpAddress")) is True or str(R(P.get("AssociatePublicIpAddress"))).lower() == "true":
            dims.append(public_ip(lid, t, 1, region))
        return dims, None, None

    if t == "AWS::AutoScaling::AutoScalingGroup":
        count = R(P.get("DesiredCapacity")) or R(P.get("MinSize")) or 1
        count = int(float(count))
        lt_ref = (P.get("LaunchTemplate") or {}).get("LaunchTemplateId") or (P.get("LaunchTemplate") or {}).get("LaunchTemplateName")
        target = ref_target(lt_ref)
        lt = resources.get(target or "", {}).get("Properties", {}).get("LaunchTemplateData", {}) if target else {}
        it = str(R(lt.get("InstanceType", P.get("InstanceType", "?"))))
        dims.append(Dim(lid, t, f"{it} × {count} · Linux (assumed)", "AmazonEC2",
                        {"regionCode": region, "instanceType": it, "tenancy": "Shared", "operatingSystem": "Linux",
                         "preInstalledSw": "NA", "capacitystatus": "Used", "licenseModel": "No License required"},
                        "Hrs", count, True))
        dims += ebs_dims(lid, t, R(lt.get("BlockDeviceMappings")), region, count, R)
        return dims, None, None

    if t == "AWS::EC2::Volume":
        dims += ebs_dims(lid, t, [{"Ebs": P}], region, 1, R)
        for d in dims:
            d.row = d.row.replace(" · volume 1", "")
        return dims, None, None

    if t == "AWS::EC2::NatGateway":
        dims.append(Dim(lid, t, "1 gateway (GB processed usage-based)", "AmazonEC2",
                        {"usagetype": up(region, "NatGateway-Hours")}, "Hrs", 1, True))
        return dims, None, None

    if t == "AWS::EC2::EIP":
        return [public_ip(lid, t, 1, region)], None, None

    if t == "AWS::ElasticLoadBalancingV2::LoadBalancer":
        kind = str(R(P.get("Type", "application")))
        op = {"application": "LoadBalancing:Application", "network": "LoadBalancing:Network",
              "gateway": "LoadBalancing:Gateway"}[kind]
        dims.append(Dim(lid, t, f"{kind} load balancer (LCU usage-based)", "AWSELB",
                        {"regionCode": region, "usagetype": up(region, "LoadBalancerUsage"), "operation": op},
                        "Hrs", 1, True))
        if str(R(P.get("Scheme", "internet-facing"))) == "internet-facing" and kind != "gateway":
            subnets = R(P.get("Subnets")) or R(P.get("SubnetMappings")) or []
            n = len(subnets) if isinstance(subnets, list) else 2
            dims.append(public_ip(f"{lid} · public IPv4", t, n, region))
        return dims, None, None

    if t == "AWS::RDS::DBInstance":
        eng_raw = str(R(P.get("Engine", ""))).lower()
        engine = RDS_ENGINE.get(eng_raw, eng_raw)
        cls = str(R(P.get("DBInstanceClass", "?")))
        maz = R(P.get("MultiAZ", False))
        maz = maz is True or str(maz).lower() == "true"
        dep = "Multi-AZ" if maz else "Single-AZ"
        aurora = engine.startswith("Aurora")
        lic = "No license required" if engine in ("MySQL", "PostgreSQL", "MariaDB") or aurora else str(R(P.get("LicenseModel", "License included")))
        f = {"regionCode": region, "instanceType": cls, "databaseEngine": engine,
             "deploymentOption": "Single-AZ" if aurora else dep}
        if not aurora:
            f["licenseModel"] = lic if lic in ("No license required", "License included", "Bring your own license") else "License included"
        dims.append(Dim(lid, t, f"{cls} · {engine} · {dep}", "AmazonRDS", f, "Hrs", 1, True))
        if not aurora and P.get("AllocatedStorage") is not None:
            size = float(R(P["AllocatedStorage"]))
            vt = str(R(P.get("StorageType", "gp2")))
            dims.append(Dim(f"{lid} · storage", t, f"{int(size)} GiB {vt} · {dep}", "AmazonRDS",
                            {"regionCode": region, "productFamily": "Database Storage",
                             "volumeType": RDS_VOLUME.get(vt, vt), "deploymentOption": dep}, "GB-Mo", size, False))
            iops = R(P.get("Iops"))
            if vt == "io1" and iops:
                dims.append(Dim(f"{lid} · IOPS", t, f"{int(float(iops))} provisioned IOPS · {dep}", "AmazonRDS",
                                {"regionCode": region, "productFamily": "Provisioned IOPS", "deploymentOption": dep},
                                "IOPS-Mo", float(iops), False))
        mmp = R(P.get("ManageMasterUserPassword"))
        if mmp is True or str(mmp).lower() == "true":
            dims.append(Dim(f"{lid} · master secret", t, "implicit Secrets Manager secret", "AWSSecretsManager",
                            {"usagetype": up(region, "AWSSecretsManager-Secrets")}, "Secrets", 1, False))
        return dims, None, None

    if t == "AWS::RDS::DBCluster":
        sv2 = R(P.get("ServerlessV2ScalingConfiguration"))
        if isinstance(sv2, dict):
            lo, hi = float(R(sv2.get("MinCapacity", 0.5))), float(R(sv2.get("MaxCapacity", 1)))
            d = Dim(lid, t, f"Aurora Serverless v2 · {lo}–{hi} ACU (priced at min; max = ×{hi / lo:.1f})", "AmazonRDS",
                    {"usagetype": up(region, "Aurora:ServerlessV2Usage")}, "ACU-Hr", lo, True)
            return [d], None, None
        if P.get("DBClusterInstanceClass"):
            eng_raw = str(R(P.get("Engine", ""))).lower()
            cls = str(R(P["DBClusterInstanceClass"]))
            d = Dim(lid, t, f"{cls} · {RDS_ENGINE.get(eng_raw, eng_raw)} · Multi-AZ DB cluster", "AmazonRDS",
                    {"regionCode": region, "instanceType": cls, "databaseEngine": RDS_ENGINE.get(eng_raw, eng_raw),
                     "deploymentOption": "Multi-AZ (readable standbys)"}, "Hrs", 1, True)
            return [d], None, None
        return [], "Aurora storage GB-Mo + I/O (instances priced on their own rows)", None

    if t in ("AWS::ElastiCache::CacheCluster", "AWS::ElastiCache::ReplicationGroup"):
        node = str(R(P.get("CacheNodeType", "?")))
        eng = CACHE_ENGINE.get(str(R(P.get("Engine", "redis"))).lower(), "Redis")
        if t == "AWS::ElastiCache::CacheCluster":
            n = int(float(R(P.get("NumCacheNodes", 1))))
        else:
            n = R(P.get("NumCacheClusters"))
            if n is None:
                n = int(float(R(P.get("NumNodeGroups", 1)))) * (int(float(R(P.get("ReplicasPerNodeGroup", 0)))) + 1)
            n = int(float(n))
        dims.append(Dim(lid, t, f"{node} · {eng} × {n} nodes", "AmazonElastiCache",
                        {"regionCode": region, "instanceType": node, "cacheEngine": eng}, "Hrs", n, True))
        return dims, None, None

    if t == "AWS::DynamoDB::Table":
        mode = str(R(P.get("BillingMode", "PROVISIONED")))
        if mode == "PAY_PER_REQUEST":
            return [], USAGE_BASED["AWS::DynamoDB::Table(PAY_PER_REQUEST)"], None
        rcu = wcu = 0.0
        for pt in [P.get("ProvisionedThroughput")] + [g.get("ProvisionedThroughput") for g in (R(P.get("GlobalSecondaryIndexes")) or [])]:
            pt = R(pt) or {}
            rcu += float(R(pt.get("ReadCapacityUnits", 0)) or 0)
            wcu += float(R(pt.get("WriteCapacityUnits", 0)) or 0)
        dims.append(Dim(f"{lid} · RCU", t, f"{int(rcu)} RCU provisioned", "AmazonDynamoDB",
                        {"usagetype": up(region, "ReadCapacityUnit-Hrs")}, "ReadCapacityUnit-Hrs", rcu, True))
        dims.append(Dim(f"{lid} · WCU", t, f"{int(wcu)} WCU provisioned", "AmazonDynamoDB",
                        {"usagetype": up(region, "WriteCapacityUnit-Hrs")}, "WriteCapacityUnit-Hrs", wcu, True))
        return dims, None, None

    if t == "AWS::OpenSearchService::Domain":
        cc = R(P.get("ClusterConfig")) or {}
        it = str(R(cc.get("InstanceType", "?")))
        n = int(float(R(cc.get("InstanceCount", 1))))
        dims.append(Dim(lid, t, f"{it} × {n} data nodes", "AmazonES",
                        {"regionCode": region, "instanceType": it}, "Hrs", n, True))
        if R(cc.get("DedicatedMasterEnabled")):
            mt, mc = str(R(cc.get("DedicatedMasterType", it))), int(float(R(cc.get("DedicatedMasterCount", 3))))
            dims.append(Dim(f"{lid} · dedicated master", t, f"{mt} × {mc}", "AmazonES",
                            {"regionCode": region, "instanceType": mt}, "Hrs", mc, True))
        ebs = R(P.get("EBSOptions")) or {}
        if R(ebs.get("EBSEnabled")) and ebs.get("VolumeSize"):
            vt = str(R(ebs.get("VolumeType", "gp3"))).upper()
            size = float(R(ebs["VolumeSize"])) * n
            dims.append(Dim(f"{lid} · EBS", t, f"{int(size)} GiB {vt.lower()} total", "AmazonES",
                            {"usagetype": up(region, f"ES:{vt}-Storage")}, "GB-Mo", size, False))
        return dims, None, None

    if t == "AWS::EKS::Cluster":
        return [Dim(lid, t, f"1 cluster (version {R(P.get('Version', '?'))}; extended-support tier not detected)", "AmazonEKS",
                    {"usagetype": up(region, "AmazonEKS-Hours:perCluster")}, "Hrs", 1, True)], None, None

    if t in ("AWS::KMS::Key", "AWS::KMS::ReplicaKey"):
        return [Dim(lid, t, "1 customer managed key", "awskms", {"usagetype": up(region, "KMS-Keys")}, "Keys", 1, False)], None, None

    if t == "AWS::SecretsManager::Secret":
        return [Dim(lid, t, "1 secret", "AWSSecretsManager", {"usagetype": up(region, "AWSSecretsManager-Secrets")}, "Secrets", 1, False)], None, None

    if t == "AWS::CloudWatch::Alarm":
        hi = float(R(P.get("Period", 60)) or 60) < 60
        return [Dim(lid, t, "high-resolution alarm" if hi else "standard alarm", "AmazonCloudWatch",
                    {"usagetype": up(region, "CW:HighResAlarmMonitorUsage" if hi else "CW:AlarmMonitorUsage")},
                    "Alarms", 1, False)], None, None

    if t == "AWS::Kinesis::Stream" and (R((P.get("StreamModeDetails") or {}).get("StreamMode")) or "PROVISIONED") == "PROVISIONED":
        n = int(float(R(P.get("ShardCount", 1))))
        return [Dim(lid, t, f"{n} shards", "AmazonKinesis", {"usagetype": up(region, "Storage-ShardHour")}, "ShardHour", n, True)], None, None

    if t in USAGE_BASED:
        return [], USAGE_BASED[t], None
    return [], None, "no charge"


def public_ip(row: str, rtype: str, n: int, region: str) -> Dim:
    return Dim(row, rtype, f"{n} public IPv4 address{'es' if n > 1 else ''}", "AmazonVPC",
               {"usagetype": up(region, "PublicIPv4:InUseAddress")}, "Hrs", n, True)


# ------------------------------------------------------------- pricing -----
class Pricer:
    def __init__(self, profile: str | None, verbose: bool):
        self.cache: dict[str, tuple[float | None, str, str, str]] = {}
        self.client = None
        self.available = True
        self.error = ""
        self.verbose = verbose
        try:
            import boto3  # type: ignore
            session = boto3.Session(profile_name=profile) if profile else boto3.Session()
            self.client = session.client("pricing", region_name="us-east-1")
            self.client.describe_services(ServiceCode="AmazonEC2", MaxResults=1)
        except Exception as e:  # noqa: BLE001
            self.available, self.error = False, f"{type(e).__name__}: {str(e)[:140]}"

    def rate(self, d: Dim) -> tuple[float | None, str, str, str]:
        k = d.key()
        if k in self.cache:
            return self.cache[k]
        res = self._lookup(d.service, d.filters)
        self.cache[k] = res
        return res

    def _lookup(self, service: str, filters: dict) -> tuple[float | None, str, str, str]:
        fl = [{"Type": "TERM_MATCH", "Field": k, "Value": str(v)} for k, v in filters.items()]
        try:
            prods = []
            kw: dict[str, Any] = {"ServiceCode": service, "Filters": fl, "MaxResults": 100}
            while True:
                r = self.client.get_products(**kw)
                prods += [json.loads(p) for p in r.get("PriceList", [])]
                if not r.get("NextToken") or len(prods) > 300:
                    break
                kw["NextToken"] = r["NextToken"]
        except Exception as e:  # noqa: BLE001
            return None, "", "not priced", f"API error {type(e).__name__}"
        if self.verbose:
            print(f"  pricing:GetProducts {service} {json.dumps(filters)} → {len(prods)} product(s)", file=sys.stderr)
        prices: dict[str, str] = {}
        for p in prods:
            for term in (p.get("terms", {}).get("OnDemand") or {}).values():
                for pd in term.get("priceDimensions", {}).values():
                    if str(pd.get("beginRange")) in ("0", "0.0"):
                        usd = pd.get("pricePerUnit", {}).get("USD")
                        if usd is not None and float(usd) > 0:
                            prices[usd] = pd.get("unit", "")
        if not prices:
            return None, "", "not priced", "0 products" if not prods else "no On-Demand dimension at beginRange 0"
        if len(prices) > 1:
            return None, "", "ambiguous", f"{len(prices)} distinct prices: " + ", ".join(sorted(prices)[:4])
        (usd, unit), = prices.items()
        return float(usd), unit, "priced", ""


# --------------------------------------------------------------- main ------
def fmt_money(x: float | None, sign: bool = False) -> str:
    if x is None:
        return ""
    s = f"${abs(x):,.2f}"
    return ("+" if x >= 0 else "−") + s if sign else s


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--template", required=True, help="path to the template in the working tree")
    ap.add_argument("--base", default="origin/main", help="git ref for the base version (default origin/main)")
    ap.add_argument("--region", required=True, help="target Region the stack deploys to")
    ap.add_argument("--account", default="unknown")
    ap.add_argument("--stack", default="")
    ap.add_argument("--profile", default=None, help="AWS profile for the Price List API")
    ap.add_argument("--param", action="append", default=[], help="Key=Value parameter override")
    ap.add_argument("--worksheet", action="store_true", help="always print the JSON worksheet")
    ap.add_argument("--no-pricing", action="store_true", help="worksheet mode: skip the Price List API")
    ap.add_argument("--verbose", action="store_true")
    a = ap.parse_args()

    overrides = dict(kv.split("=", 1) for kv in a.param)
    head = load_template(open(a.template, encoding="utf-8").read())
    base = load_template(git_show(a.base, a.template))
    hp, bp = param_values(head, overrides), param_values(base, overrides)
    hres, bres = head.get("Resources") or {}, base.get("Resources") or {}

    def dims_for(resources: dict, params: dict):
        fixed, usage, free = [], [], []
        for lid, res in resources.items():
            try:
                d, u, n = extract(lid, res, resources, params, a.region)
            except Exception as e:  # noqa: BLE001
                d, u, n = [], None, f"extraction failed: {e}"
            fixed += d
            if u:
                usage.append((lid, res.get("Type", ""), u))
            elif n and not d:
                free.append((lid, res.get("Type", ""), n))
        return fixed, usage, free

    hf, hu, hn = dims_for(hres, hp)
    bf, _, _ = dims_for(bres, bp)
    bmap = {d.row: d for d in bf}

    rows = []  # (change, dim, old_dim)
    for d in hf:
        lid = d.row.split(" · ")[0]
        if lid not in bres:
            rows.append(("Add", d, None))
        elif repr(bres[lid]) != repr(hres[lid]):
            rows.append(("Modify", d, bmap.get(d.row)))
    for d in bf:
        lid = d.row.split(" · ")[0]
        if lid not in hres:
            rows.append(("Remove", d, None))
        elif d.row not in {x.row for x in hf} and repr(bres[lid]) != repr(hres[lid]):
            rows.append(("Modify", Dim(d.row, d.rtype, "removed dimension", d.service, d.filters, d.unit_hint, 0, d.hourly), d))
    mod_usage = [(lid, t, u) for lid, t, u in hu if lid in bres and repr(bres[lid]) != repr(hres[lid])]
    add_usage = [(lid, t, u) for lid, t, u in hu if lid not in bres]
    add_free = [(lid, t, n) for lid, t, n in hn if lid not in bres]

    pricer = None if a.no_pricing else Pricer(a.profile, a.verbose)
    live = pricer is not None and pricer.available
    if live:
        for _, d, old in rows:
            d.rate, unit, d.status, d.note = pricer.rate(d)
            d.unit = unit or d.unit_hint
            if old is not None:
                old.rate, ounit, old.status, old.note = pricer.rate(old)
                old.unit = ounit or old.unit_hint

    when = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    base_exists = bool(bres)
    changes = f"static diff `{a.base}` → working tree" + ("" if base_exists else " (template new at base: every resource is an Add)")
    stack = f"stack `{a.stack}` · " if a.stack else ""
    if live:
        mode = f"Mode: full · {changes} · rates: live AWS Price List, {when} · {HOURS} h/month"
    else:
        why = "--no-pricing" if a.no_pricing else f"no AWS credentials for the Price List API ({pricer.error})"
        mode = f"Mode: worksheet ({why}) · {changes} · rates: pending · {HOURS} h/month"

    print(f"### IaC change cost preview: `{a.template}` · {stack}account {a.account} · {a.region}\n")
    print(mode + "\n")
    print("| Resource | Type | Change | Sizing | Rate | Monthly cost |")
    print("|---|---|---|---|---|---:|")

    def cost_cell(d: Dim, old: Dim | None, change: str) -> tuple[str, float | None]:
        if not live:
            return "pending", None
        if d.status != "priced" and change != "Remove":
            return f"not priced ({d.status}: {d.note})", None
        m = d.monthly() if d.status == "priced" else None
        if change == "Remove":
            return (fmt_money(-m, True), -m) if m is not None else (f"not priced ({d.note})", None)
        if change == "Modify":
            om = old.monthly() if (old and old.status == "priced") else 0.0
            delta = m - om
            return fmt_money(delta, True), delta
        return fmt_money(m), m

    total, pending, unpriced = 0.0, 0, 0
    table = []
    for change, d, old in rows:
        cell, val = cost_cell(d, old, change)
        if val is not None:
            total += val
        elif cell == "pending":
            pending += 1
        else:
            unpriced += 1
        hint = d.filters.get("usagetype") or d.filters.get("instanceType") or d.filters.get("volumeApiName") or d.filters.get("volumeType") or d.filters.get("operation") or ""
        rate = f"${d.rate:,.5f} / {d.unit}" if d.rate is not None else f"{d.service} · {hint}"
        sizing = d.sizing if change != "Modify" or old is None else f"{old.sizing} → {d.sizing}"
        table.append((val if val is not None else -1e18, f"| {d.row} | `{d.rtype}` | {change} | {sizing} | {rate} | {cell} |"))
    for _, line in sorted(table, key=lambda x: -x[0]):
        print(line)
    for lid, t, u in add_usage:
        print(f"| {lid} | `{t}` | Add | — | {u} | usage-based |")
    for lid, t, u in mod_usage:
        print(f"| {lid} | `{t}` | Modify | — | {u} | usage-based (no fixed delta) |")
    for lid, t, n in add_free:
        print(f"| {lid} | `{t}` | Add | — | — | no charge |")
    if live:
        tail = f"**{fmt_money(total, True)} / month**" + (f" · {unpriced} row(s) not priced" if unpriced else "")
    else:
        tail = f"**pending ({pending} rows)**"
    print(f"| **Total fixed monthly estimate** | | | | | {tail} |\n")

    if live:
        src = "; ".join(f"{d.row} → {d.service} {json.dumps(d.filters, separators=(',', ':'))} ({d.unit})"
                        for _, d, _ in rows if d.rate is not None)
        print(f"Rate sources: {src}\n")
    defaulted = [k for k, v in (head.get("Parameters") or {}).items() if k not in overrides and "Default" in v]
    print(f"Assumptions: parameters defaulted: {', '.join(defaulted) or 'none'} · OS assumed Linux for EC2 rows · "
          f"account {a.account} · change classification is static (no change set); Replacement not evaluated\n")

    if a.worksheet or not live:
        ws = {"iac_change_cost_preview_worksheet": "1", "source": f"{a.template} {a.base}..working-tree",
              "stack": a.stack or None, "account": a.account, "region": a.region, "changes_from": "static diff",
              "hours_per_month": HOURS,
              "rows": [{"resource": d.row, "type": d.rtype, "change": c, "service_code": d.service, "filters": d.filters,
                        "quantity": d.qty, "unit": d.unit_hint, "formula": "rate * 730 * quantity" if d.hourly else "rate * quantity",
                        **({"old_quantity": old.qty} if old else {})} for c, d, old in rows],
              "usage_based": [{"resource": lid, "type": t, "dimensions": u} for lid, t, u in add_usage + mod_usage],
              "assumptions": [f"parameters defaulted: {', '.join(defaulted) or 'none'}", f"account {a.account}"]}
        print("Pricing worksheet:\n\n```json\n" + json.dumps(ws, indent=2) + "\n```")
    return 0


if __name__ == "__main__":
    sys.exit(main())
