interface ClaudeCodeInstallerOptions {
  endpoint: string;
  token: string;
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

export function buildClaudeCodeInstaller({ endpoint, token }: ClaudeCodeInstallerOptions): string {
  const safeEndpoint = requireHttpUrl(endpoint, 'MCP endpoint');
  if (!/^sbmcp_[A-Za-z0-9._~-]+$/.test(token)) {
    throw new Error('MCP token is invalid');
  }

  const script = [
    "$ErrorActionPreference='Stop'",
    'try {',
    '[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)',
    `$endpoint=${quotePowerShell(safeEndpoint)}`,
    `$token=${quotePowerShell(token)}`,
    "$server='smartbrain-company-memory'",
    "$authHeader='Authorization: Bearer ${SMARTBRAIN_WIKI_MCP_TOKEN}'",
    "[Environment]::SetEnvironmentVariable('SMARTBRAIN_WIKI_MCP_TOKEN',$token,'User')",
    "if([Environment]::GetEnvironmentVariable('SMARTBRAIN_WIKI_MCP_TOKEN','User') -ne $token){throw 'Failed to persist the SmartBrain MCP token.'}",
    '$env:SMARTBRAIN_WIKI_MCP_TOKEN=$token',
    '$claude=(Get-Command claude.cmd -ErrorAction SilentlyContinue).Source',
    'if(!$claude){$claude=(Get-Command claude.exe -ErrorAction SilentlyContinue).Source}',
    "if(!$claude){throw 'Claude Code is not installed or is not in PATH.'}",
    '$previousErrorActionPreference=$ErrorActionPreference',
    "$ErrorActionPreference='Continue'",
    '& $claude mcp remove --scope user $server 2>&1|Out-Null',
    '$ErrorActionPreference=$previousErrorActionPreference',
    '$global:LASTEXITCODE=0',
    '& $claude mcp add --transport http --scope user $server $endpoint --header $authHeader',
    "if($LASTEXITCODE -ne 0){throw 'Failed to configure the SmartBrain MCP server in Claude Code.'}",
    '& $claude mcp get $server|Out-Host',
    "if($LASTEXITCODE -ne 0){throw 'Claude Code could not read the new SmartBrain MCP configuration.'}",
    "[Console]::WriteLine('SmartBrain Company Memory MCP configured. Restart Claude Code or start a new session.')",
    "Read-Host 'Press Enter to close'|Out-Null",
    'exit 0',
    '} catch {',
    "[Console]::WriteLine('Installation failed: '+$_.Exception.Message)",
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

export function downloadClaudeCodeInstaller(options: ClaudeCodeInstallerOptions): void {
  const content = buildClaudeCodeInstaller(options);
  const blob = new Blob([content], { type: 'application/x-msdos-program;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = 'SmartBrain-Claude-Code-MCP-Setup.cmd';
  anchor.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}
