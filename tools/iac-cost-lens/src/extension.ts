import * as vscode from 'vscode';
import * as cp from 'child_process';
import * as fs from 'fs';
import * as os from 'os';
import * as path from 'path';

// ---- shape of `cost_preview.py --format json` -------------------------------
interface Row {
  row: string; logical_id: string; type: string; change: string; sizing: string;
  service_code: string; rate: number | null; unit: string; quantity: number;
  status: string; note: string; monthly: number | null; cell: string;
}
interface Result {
  template: string; stack: string; account: string; region: string; base: string; head: string;
  mode: 'full' | 'worksheet'; mode_reason: string; generated_at: string;
  rows: Row[];
  usage_based: { logical_id: string; type: string; change: string; dimensions: string }[];
  no_charge: { logical_id: string; type: string }[];
  total_fixed_monthly: number | null; pending_rows: number; unpriced_rows: number;
  max_monthly_delta: number | null;
}

const money = (x: number, sign = false) => {
  const s = `$${Math.abs(x).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  return sign ? (x >= 0 ? '+' : '−') + s : s;
};

class CostLensProvider implements vscode.CodeLensProvider {
  private readonly changed = new vscode.EventEmitter<void>();
  readonly onDidChangeCodeLenses = this.changed.event;
  private readonly results = new Map<string, Result>();   // doc uri → last result
  private readonly errors = new Map<string, string>();
  private readonly timers = new Map<string, NodeJS.Timeout>();
  private readonly running = new Set<string>();
  readonly status: vscode.StatusBarItem;
  readonly output = vscode.window.createOutputChannel('IaC Cost Lens');

  constructor() {
    this.status = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 50);
    this.status.command = 'iacCostLens.showTable';
  }

  private cfg<T>(key: string, doc?: vscode.TextDocument): T {
    return vscode.workspace.getConfiguration('iacCostLens', doc?.uri).get<T>(key) as T;
  }

  matches(doc: vscode.TextDocument): boolean {
    if (!this.cfg<boolean>('enabled', doc)) return false;
    if (doc.uri.scheme !== 'file') return false;
    return vscode.languages.match({ pattern: this.cfg<string>('filePattern', doc) }, doc) > 0;
  }

  /** Re-run the estimate after the debounce window; unsaved text is priced via --head-file. */
  schedule(doc: vscode.TextDocument, immediate = false): void {
    if (!this.matches(doc)) return;
    const key = doc.uri.toString();
    clearTimeout(this.timers.get(key));
    const run = () => void this.run(doc);
    if (immediate) run(); else this.timers.set(key, setTimeout(run, this.cfg<number>('debounceMs', doc)));
  }

  private async run(doc: vscode.TextDocument): Promise<void> {
    const key = doc.uri.toString();
    if (this.running.has(key)) { this.schedule(doc); return; }
    const folder = vscode.workspace.getWorkspaceFolder(doc.uri);
    if (!folder) return;
    const root = folder.uri.fsPath;
    const script = path.resolve(root, this.cfg<string>('scriptPath', doc));
    if (!fs.existsSync(script)) { this.errors.set(key, `script not found: ${script}`); this.refresh(doc); return; }
    const rel = path.relative(root, doc.uri.fsPath).split(path.sep).join('/');

    this.running.add(key);
    this.status.text = '$(sync~spin) IaC cost: pricing…';
    this.status.show();
    const tmp = path.join(os.tmpdir(), `iac-cost-lens-${process.pid}-${Date.now()}.tpl`);
    try {
      fs.writeFileSync(tmp, doc.getText(), 'utf8');
      const args = [script, '--template', rel, '--head-file', tmp, '--base', this.cfg<string>('baseRef', doc),
        '--config', this.cfg<string>('configPath', doc), '--format', 'json'];
      const profile = this.cfg<string>('awsProfile', doc);
      if (profile) args.push('--profile', profile);
      const out = await this.exec(this.cfg<string>('pythonPath', doc), args, root);
      const res = JSON.parse(out) as Result;
      this.results.set(key, res);
      this.errors.delete(key);
      this.output.appendLine(`[${res.generated_at}] ${rel}: mode=${res.mode} rows=${res.rows.length} total=${res.total_fixed_monthly ?? 'pending'}`);
    } catch (e) {
      const msg = (e as Error).message.split('\n').slice(-3).join(' ').slice(0, 300);
      this.errors.set(key, msg);
      this.output.appendLine(`${rel}: ${msg}`);
    } finally {
      try { fs.unlinkSync(tmp); } catch { /* ignore */ }
      this.running.delete(key);
      this.refresh(doc);
    }
  }

  private exec(cmd: string, args: string[], cwd: string): Promise<string> {
    return new Promise((resolve, reject) => {
      cp.execFile(cmd, args, { cwd, maxBuffer: 20 * 1024 * 1024, env: process.env }, (err, stdout, stderr) => {
        // exit 2 = over the configured limit; the JSON is still complete
        const code = (err as (cp.ExecFileException & { code?: number | string }) | null)?.code;
        if (err && String(code) !== '2') {
          reject(new Error(stderr || err.message)); return;
        }
        resolve(stdout);
      });
    });
  }

  private refresh(doc: vscode.TextDocument): void {
    this.changed.fire();
    this.updateStatus(doc);
  }

  updateStatus(doc: vscode.TextDocument | undefined): void {
    if (!doc || !this.matches(doc)) { this.status.hide(); return; }
    const key = doc.uri.toString();
    const err = this.errors.get(key);
    const res = this.results.get(key);
    if (err) { this.status.text = '$(warning) IaC cost: error'; this.status.tooltip = err; this.status.show(); return; }
    if (!res) { this.status.hide(); return; }
    if (res.mode !== 'full') {
      this.status.text = `$(key) IaC cost: pending (${res.pending_rows} rows)`;
      this.status.tooltip = `Price List API unreachable: ${res.mode_reason}\nRefresh AWS credentials, then save the file.`;
    } else {
      const t = res.total_fixed_monthly ?? 0;
      const over = res.max_monthly_delta !== null && t > res.max_monthly_delta;
      this.status.text = `${over ? '$(error)' : '$(graph)'} IaC cost ${money(t, true)}/mo` +
        (res.unpriced_rows ? ` · ${res.unpriced_rows} not priced` : '');
      this.status.tooltip = `Fixed monthly delta vs ${res.base} · ${res.region} · live rates ${res.generated_at}` +
        (over ? `\nExceeds limit ${money(res.max_monthly_delta!)}` : '') + '\nClick for the full table';
    }
    this.status.show();
  }

  /** Line of every `  <LogicalId>:` directly under Resources (YAML) or `"<LogicalId>": {` inside "Resources" (JSON). */
  private resourceLines(doc: vscode.TextDocument): Map<string, number> {
    const lines = new Map<string, number>();
    const text = doc.getText();
    if (doc.languageId === 'json' || text.trimStart().startsWith('{')) {
      const m = /"Resources"\s*:\s*\{/.exec(text);
      if (!m) return lines;
      const re = /^\s*"([A-Za-z0-9]+)"\s*:\s*\{/gm;
      re.lastIndex = m.index + m[0].length;
      let depth = 1; let r: RegExpExecArray | null;
      // shallow scan: logical ids are the keys one level below Resources
      while ((r = re.exec(text))) {
        const before = text.slice(m.index + m[0].length, r.index);
        depth = 1 + (before.match(/\{/g)?.length ?? 0) - (before.match(/\}/g)?.length ?? 0);
        if (depth <= 0) break;
        if (depth === 1) lines.set(r[1], doc.positionAt(r.index).line);
      }
      return lines;
    }
    let inResources = false; let indent = -1;
    for (let i = 0; i < doc.lineCount; i++) {
      const l = doc.lineAt(i).text;
      if (/^Resources\s*:/.test(l)) { inResources = true; indent = -1; continue; }
      if (!inResources) continue;
      if (/^\S/.test(l) && !/^\s*#/.test(l)) break;               // next top-level section
      const m = /^(\s+)([A-Za-z0-9]+)\s*:\s*(#.*)?$/.exec(l);
      if (!m) continue;
      if (indent < 0) indent = m[1].length;
      if (m[1].length === indent) lines.set(m[2], i);
    }
    return lines;
  }

  provideCodeLenses(doc: vscode.TextDocument): vscode.CodeLens[] {
    if (!this.matches(doc)) return [];
    const key = doc.uri.toString();
    const res = this.results.get(key);
    const err = this.errors.get(key);
    const at = this.resourceLines(doc);
    const lens = (line: number, title: string, tooltip?: string) => {
      const l = new vscode.CodeLens(new vscode.Range(line, 0, line, 0), { title, command: 'iacCostLens.showTable', tooltip });
      return l;
    };
    const out: vscode.CodeLens[] = [];
    if (err) {
      for (const [, line] of at) { out.push(lens(line, `⚠ IaC cost: ${err.slice(0, 80)}`)); break; }
      return out;
    }
    if (!res) {
      if (!this.running.has(key)) this.schedule(doc, true);
      return [];
    }
    // group fixed rows by logical id
    const byId = new Map<string, Row[]>();
    for (const r of res.rows) byId.set(r.logical_id, [...(byId.get(r.logical_id) ?? []), r]);
    for (const [id, rows] of byId) {
      const line = at.get(id); if (line === undefined) continue;
      const change = rows[0].change;
      if (res.mode !== 'full') {
        out.push(lens(line, `$(key) cost pending · ${rows.map(r => r.sizing).join(' · ')}`, 'Price List API unreachable: refresh AWS credentials'));
        continue;
      }
      const priced = rows.filter(r => r.monthly !== null);
      const sum = priced.reduce((a, r) => a + (r.monthly ?? 0), 0);
      const unpriced = rows.length - priced.length;
      let title = priced.length
        ? `${change === 'Add' ? '+' : ''}${money(sum, change !== 'Add')} / month`
        : `not priced`;
      if (unpriced && priced.length) title += ` · ${unpriced} dimension${unpriced > 1 ? 's' : ''} not priced`;
      title += ` · ${rows[0].sizing}` + (change !== 'Add' ? ` · ${change}` : '');
      const tip = rows.map(r => `${r.row}: ${r.cell}` + (r.rate !== null ? ` (${r.service_code} $${r.rate}/${r.unit} × ${r.quantity})` : ` (${r.status}${r.note ? ': ' + r.note : ''})`)).join('\n')
        + `\nlive rates ${res.generated_at} · ${res.region}`;
      out.push(lens(line, title, tip));
    }
    for (const u of res.usage_based) {
      const line = at.get(u.logical_id); if (line === undefined) continue;
      out.push(lens(line, `usage-based · ${u.dimensions}` + (u.change === 'Modify' ? ' · Modify' : ''), 'Not estimated: depends on traffic or data volume'));
    }
    for (const n of res.no_charge) {
      const line = at.get(n.logical_id); if (line === undefined) continue;
      out.push(lens(line, 'no charge'));
    }
    return out;
  }

  async showTable(doc: vscode.TextDocument | undefined): Promise<void> {
    if (!doc || !this.matches(doc)) { vscode.window.showInformationMessage('IaC Cost Lens: open a CloudFormation template first.'); return; }
    const folder = vscode.workspace.getWorkspaceFolder(doc.uri); if (!folder) return;
    const root = folder.uri.fsPath;
    const script = path.resolve(root, this.cfg<string>('scriptPath', doc));
    const rel = path.relative(root, doc.uri.fsPath).split(path.sep).join('/');
    const tmp = path.join(os.tmpdir(), `iac-cost-lens-${Date.now()}.tpl`);
    fs.writeFileSync(tmp, doc.getText(), 'utf8');
    try {
      const args = [script, '--template', rel, '--head-file', tmp, '--base', this.cfg<string>('baseRef', doc),
        '--config', this.cfg<string>('configPath', doc), '--format', 'markdown'];
      const profile = this.cfg<string>('awsProfile', doc); if (profile) args.push('--profile', profile);
      const md = await this.exec(this.cfg<string>('pythonPath', doc), args, root);
      const d = await vscode.workspace.openTextDocument({ content: md, language: 'markdown' });
      await vscode.commands.executeCommand('markdown.showPreviewToSide', d.uri);
    } catch (e) {
      vscode.window.showErrorMessage(`IaC Cost Lens: ${(e as Error).message.slice(0, 300)}`);
    } finally { try { fs.unlinkSync(tmp); } catch { /* ignore */ } }
  }
}

export function activate(ctx: vscode.ExtensionContext): void {
  const p = new CostLensProvider();
  ctx.subscriptions.push(
    p.status, p.output,
    vscode.languages.registerCodeLensProvider([{ language: 'yaml', scheme: 'file' }, { language: 'json', scheme: 'file' }], p),
    vscode.workspace.onDidChangeTextDocument(e => p.schedule(e.document)),
    vscode.workspace.onDidSaveTextDocument(d => p.schedule(d, true)),
    vscode.workspace.onDidOpenTextDocument(d => p.schedule(d, true)),
    vscode.window.onDidChangeActiveTextEditor(e => p.updateStatus(e?.document)),
    vscode.commands.registerCommand('iacCostLens.refresh', () => { const d = vscode.window.activeTextEditor?.document; if (d) p.schedule(d, true); }),
    vscode.commands.registerCommand('iacCostLens.showTable', () => p.showTable(vscode.window.activeTextEditor?.document)),
    vscode.commands.registerCommand('iacCostLens.toggle', async () => {
      const c = vscode.workspace.getConfiguration('iacCostLens');
      await c.update('enabled', !c.get<boolean>('enabled'), vscode.ConfigurationTarget.Global);
      const d = vscode.window.activeTextEditor?.document; if (d) p.schedule(d, true);
    }),
  );
  const d = vscode.window.activeTextEditor?.document; if (d) p.schedule(d, true);
}

export function deactivate(): void { /* nothing to clean up */ }
