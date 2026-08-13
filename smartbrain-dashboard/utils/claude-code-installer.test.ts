import { describe, expect, it } from 'vitest';

import { buildClaudeCodeInstaller } from './claude-code-installer';

function decodePowerShell(commandFile: string): string {
  const match = commandFile.match(/-EncodedCommand ([A-Za-z0-9+/=]+)/);
  if (!match) throw new Error('Encoded PowerShell payload is missing');
  return Buffer.from(match[1], 'base64').toString('utf16le');
}

describe('buildClaudeCodeInstaller', () => {
  it('creates a self-deleting user-scoped Claude Code MCP installer', () => {
    const commandFile = buildClaudeCodeInstaller({
      endpoint: 'https://39.105.79.0/mcp',
      token: 'sbmcp_visible_once',
    });

    expect(commandFile).toContain('powershell.exe -NoProfile -ExecutionPolicy Bypass -EncodedCommand');
    expect(commandFile).toContain('del /f /q "%~f0"');
    expect(commandFile.length).toBeLessThan(8000);

    const script = decodePowerShell(commandFile);
    expect(script).toContain("Get-Command claude.cmd");
    expect(script).toContain("Get-Command claude.exe");
    expect(script).toContain("SetEnvironmentVariable('SMARTBRAIN_WIKI_MCP_TOKEN',$token,'User')");
    expect(script).toContain("$authHeader='Authorization: Bearer ${SMARTBRAIN_WIKI_MCP_TOKEN}'");
    expect(script).toContain("$previousErrorActionPreference=$ErrorActionPreference");
    expect(script).toContain("$ErrorActionPreference='Continue'");
    expect(script).toContain('& $claude mcp remove --scope user $server 2>&1|Out-Null');
    expect(script).toContain('$ErrorActionPreference=$previousErrorActionPreference');
    expect(script).toContain('$global:LASTEXITCODE=0');
    expect(script).toContain('mcp add --transport http --scope user $server $endpoint --header $authHeader');
    expect(script).not.toContain("Write-Host ('Installation failed:");
    expect(script).toContain('smartbrain-company-memory');
    expect(script).toContain('https://39.105.79.0/mcp');
    expect(script).toContain('Restart Claude Code or start a new session');
  });

  it('rejects unsafe endpoints and invalid tokens', () => {
    expect(() => buildClaudeCodeInstaller({
      endpoint: 'file:///tmp/mcp',
      token: 'sbmcp_visible_once',
    })).toThrow('MCP endpoint');

    expect(() => buildClaudeCodeInstaller({
      endpoint: 'https://39.105.79.0/mcp',
      token: 'not-a-wiki-token',
    })).toThrow('MCP token');
  });
});
