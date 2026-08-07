export const CODEX_PLUGIN_BUNDLE_PATH = '/downloads/smartbrain-company-memory-codex.zip';

interface CodexInstallerOptions {
  endpoint: string;
  token: string;
  bundleUrl: string;
}

function requireHttpUrl(value: string, label: string): string {
  let parsed: URL;
  try {
    parsed = new URL(value);
  } catch {
    throw new Error(`${label} is invalid`);
  }
  if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
    throw new Error(`${label} must use HTTP or HTTPS`);
  }
  return parsed.toString();
}

function quotePowerShell(value: string): string {
  return `'${value.replaceAll("'", "''")}'`;
}

function encodeUtf16Le(value: string): string {
  let binary = '';
  for (let index = 0; index < value.length; index += 1) {
    const code = value.charCodeAt(index);
    binary += String.fromCharCode(code & 0xff, code >> 8);
  }
  return btoa(binary);
}

export function buildCodexInstaller({ endpoint, token, bundleUrl }: CodexInstallerOptions): string {
  const safeEndpoint = requireHttpUrl(endpoint, 'MCP endpoint');
  const safeBundleUrl = requireHttpUrl(bundleUrl, 'Plugin bundle URL');
  if (!/^sbmcp_[A-Za-z0-9._~-]+$/.test(token)) {
    throw new Error('MCP token is invalid');
  }

  const script = [
    "$ErrorActionPreference='Stop'",
    'try {',
    "[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)",
    `$endpoint=${quotePowerShell(safeEndpoint)}`,
    `$token=${quotePowerShell(token)}`,
    `$bundle=${quotePowerShell(safeBundleUrl)}`,
    "$root=Join-Path $env:LOCALAPPDATA 'SmartBrain\\CodexPluginMarketplace'",
    "$zip=Join-Path $env:TEMP 'smartbrain-company-memory-codex.zip'",
    'if(Test-Path -LiteralPath $root){Remove-Item -LiteralPath $root -Recurse -Force}',
    'New-Item -ItemType Directory -Path $root -Force|Out-Null',
    'Invoke-WebRequest -Uri $bundle -OutFile $zip -UseBasicParsing',
    'Expand-Archive -LiteralPath $zip -DestinationPath $root -Force',
    'Remove-Item -LiteralPath $zip -Force',
    "$manifest=Join-Path $root 'plugins\\company-memory\\.codex-plugin\\plugin.json'",
    '$plugin=Get-Content -LiteralPath $manifest -Raw -Encoding UTF8|ConvertFrom-Json',
    "$plugin.mcpServers.'smartbrain-company-memory'.url=$endpoint",
    '$config=$plugin|ConvertTo-Json -Depth 8',
    '[IO.File]::WriteAllText($manifest,$config,[Text.UTF8Encoding]::new($false))',
    "[Environment]::SetEnvironmentVariable('SMARTBRAIN_WIKI_MCP_TOKEN',$token,'User')",
    "if([Environment]::GetEnvironmentVariable('SMARTBRAIN_WIKI_MCP_TOKEN','User') -ne $token){throw 'Failed to persist the SmartBrain MCP token.'}",
    '$env:SMARTBRAIN_WIKI_MCP_TOKEN=$token',
    '$codex=(Get-Command codex.cmd -ErrorAction SilentlyContinue).Source',
    'if(!$codex){$codex=(Get-Command codex.exe -ErrorAction SilentlyContinue).Source}',
    "if(!$codex){throw 'Codex CLI is not installed or is not in PATH.'}",
    "$marketplaces=(& $codex plugin marketplace list --json|ConvertFrom-Json).marketplaces",
    "if($marketplaces.name -contains 'smartbrain'){& $codex plugin marketplace remove smartbrain --json|Out-Null;if($LASTEXITCODE -ne 0){throw 'Failed to remove the previous SmartBrain plugin marketplace.'}}",
    '& $codex plugin marketplace add $root',
    "if($LASTEXITCODE -ne 0){throw 'Failed to add the SmartBrain plugin marketplace.'}",
    "& $codex plugin add 'company-memory@smartbrain'",
    "if($LASTEXITCODE -ne 0){throw 'Failed to install the company-memory plugin.'}",
    "Write-Host 'SmartBrain Company Memory installed. Completely exit Codex and ChatGPT, reopen the app, then start a new task.' -ForegroundColor Green",
    "Read-Host 'Press Enter to close'|Out-Null",
    'exit 0',
    '} catch {',
    "Write-Host ('Installation failed: '+$_.Exception.Message) -ForegroundColor Red",
    "Read-Host 'Press Enter to close'|Out-Null",
    'exit 1',
    '}',
  ].join(';');

  const payload = encodeUtf16Le(script);
  const commandFile = [
    '@echo off',
    'chcp 65001 >nul',
    `powershell.exe -NoProfile -ExecutionPolicy Bypass -EncodedCommand ${payload}`,
    'set "SMARTBRAIN_INSTALL_EXIT=%ERRORLEVEL%"',
    'if "%SMARTBRAIN_INSTALL_EXIT%"=="0" start "" /b cmd /c ping 127.0.0.1 -n 2 ^>nul ^& del /f /q "%~f0"',
    'exit /b %SMARTBRAIN_INSTALL_EXIT%',
    '',
  ].join('\r\n');

  if (commandFile.length >= 8000) {
    throw new Error('Generated installer exceeds the Windows command length limit');
  }
  return commandFile;
}

export function downloadCodexInstaller(options: CodexInstallerOptions): void {
  const content = buildCodexInstaller(options);
  const blob = new Blob([content], { type: 'application/x-msdos-program;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = 'SmartBrain-Company-Memory-Setup.cmd';
  anchor.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}
