import { describe, expect, it } from 'vitest';

import { buildCodexInstaller } from './codex-plugin-installer';

function decodePowerShell(commandFile: string): string {
  const match = commandFile.match(/-EncodedCommand ([A-Za-z0-9+/=]+)/);
  if (!match) throw new Error('Encoded PowerShell payload is missing');
  return Buffer.from(match[1], 'base64').toString('utf16le');
}

describe('buildCodexInstaller', () => {
  it('creates a self-deleting Windows installer for the complete SmartBrain plugin', () => {
    const commandFile = buildCodexInstaller({
      endpoint: 'http://192.168.1.40:8010/mcp',
      token: 'sbmcp_visible_once',
      bundleUrl: 'http://192.168.1.40:3002/downloads/smartbrain-company-memory-codex.zip',
    });

    expect(commandFile).toContain('powershell.exe -NoProfile -ExecutionPolicy Bypass -EncodedCommand');
    expect(commandFile).toContain('del /f /q "%~f0"');
    expect(commandFile.length).toBeLessThan(8000);

    const script = decodePowerShell(commandFile);
    expect(script).toContain('SMARTBRAIN_WIKI_MCP_TOKEN');
    expect(script).toContain('sbmcp_visible_once');
    expect(script).toContain('http://192.168.1.40:8010/mcp');
    expect(script).toContain('smartbrain-company-memory-codex.zip');
    expect(script).toContain('plugin marketplace list --json');
    expect(script).toContain("$marketplaces.name -contains 'smartbrain'");
    expect(script).toContain('plugin marketplace add');
    expect(script).toContain('plugin add');
    expect(script).toContain('company-memory@smartbrain');
  });

  it('rejects unsafe endpoints and invalid token values', () => {
    expect(() =>
      buildCodexInstaller({
        endpoint: 'file:///tmp/mcp',
        token: 'sbmcp_visible_once',
        bundleUrl: 'http://192.168.1.40:3002/downloads/plugin.zip',
      }),
    ).toThrow('MCP endpoint');

    expect(() =>
      buildCodexInstaller({
        endpoint: 'http://192.168.1.40:8010/mcp',
        token: 'not-a-wiki-token',
        bundleUrl: 'http://192.168.1.40:3002/downloads/plugin.zip',
      }),
    ).toThrow('MCP token');
  });
});
