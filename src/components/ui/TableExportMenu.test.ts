import { describe, expect, it } from 'vitest';
import { readExplicitTableData, readVisibleTableData, serializeTableCsv } from './TableExportMenu';

describe('TableExportMenu data contract', () => {
  it('keeps visible headers and their order while omitting actions and internal IDs', () => {
    document.body.innerHTML = `
      <table><thead><tr>
        <th>名称</th><th>资产 ID</th><th>站点ID</th><th>Provider ID</th><th>Model ID</th><th>状态</th><th class="nx-action-column-header">操作</th>
      </tr></thead><tbody><tr>
        <td>核心交换机 <small data-export-ignore>asset-123</small></td><td>asset-123</td><td>site-456</td><td>provider-123</td><td>model-456</td><td>在线</td><td>编辑</td>
      </tr></tbody></table>`;
    const table = document.querySelector('table');
    expect(table).not.toBeNull();
    expect(readVisibleTableData(table!)).toEqual({ headers: ['名称', '状态'], rows: [['核心交换机', '在线']] });
  });

  it('allows an explicit include override for a business ID column', () => {
    document.body.innerHTML = '<table><thead><tr><th data-export="include">VLAN ID</th></tr></thead><tbody><tr><td>120</td></tr></tbody></table>';
    expect(readVisibleTableData(document.querySelector('table')!)).toEqual({ headers: ['VLAN ID'], rows: [['120']] });
  });

  it('exports only the primary value when a displayed cell also contains helper text or an ID', () => {
    document.body.innerHTML = `
      <table><thead><tr><th>告警标题</th><th>对象</th></tr></thead><tbody><tr>
        <td><p><span data-export-primary>Device Offline</span><span data-export-ignore> ×9</span></p><small>设备无法连接，Ping 超时</small></td>
        <td><div data-export-primary>core-sw-01</div><div data-export-ignore>site-4a75e3a1257a</div></td>
      </tr></tbody></table>`;
    expect(readVisibleTableData(document.querySelector('table')!)).toEqual({
      headers: ['告警标题', '对象'],
      rows: [['Device Offline', 'core-sw-01']],
    });
  });

  it('keeps sensitive headers in place but blanks their exported values', () => {
    document.body.innerHTML = '<table><thead><tr><th>账号</th><th>登录密码</th><th data-export="include">API Key</th><th>Token 用量</th><th>Tokens</th></tr></thead><tbody><tr><td>admin</td><td>hunter2</td><td>sk-secret</td><td>128</td><td>56</td></tr></tbody></table>';
    expect(readVisibleTableData(document.querySelector('table')!)).toEqual({
      headers: ['账号', '登录密码', 'API Key', 'Token 用量', 'Tokens'],
      rows: [['admin', '', '', '128', '56']],
    });
  });

  it('allows public labels to override automatic sensitivity but not explicit sensitive marking', () => {
    document.body.innerHTML = '<table><thead><tr><th data-export="public">Credential</th><th data-export="sensitive">Device</th></tr></thead><tbody><tr><td>Shared account</td><td>must stay blank</td></tr></tbody></table>';
    expect(readVisibleTableData(document.querySelector('table')!)).toEqual({
      headers: ['Credential', 'Device'],
      rows: [['Shared account', '']],
    });
  });

  it('keeps credential names while blanking credential and password secrets', () => {
    document.body.innerHTML = '<table><thead><tr><th>凭据名称</th><th>Credential name</th><th>凭据</th><th>Password name</th></tr></thead><tbody><tr><td>生产只读账号</td><td>Monitoring account</td><td>secret-value</td><td>must stay blank</td></tr></tbody></table>';
    expect(readVisibleTableData(document.querySelector('table')!)).toEqual({
      headers: ['凭据名称', 'Credential name', '凭据', 'Password name'],
      rows: [['生产只读账号', 'Monitoring account', '', '']],
    });
  });

  it('blanks community and fixed PIN credentials while preserving usage metrics', () => {
    document.body.innerHTML = '<table><thead><tr><th>SNMP Community String</th><th>团体名</th><th>固定 PIN</th><th>PIN Code</th><th>Spinning Count</th><th>Token</th><th>Token Count</th></tr></thead><tbody><tr><td>public-ro</td><td>community-secret</td><td>123456</td><td>654321</td><td>7</td><td>bearer-secret</td><td>42</td></tr></tbody></table>';
    expect(readVisibleTableData(document.querySelector('table')!)).toEqual({
      headers: ['SNMP Community String', '团体名', '固定 PIN', 'PIN Code', 'Spinning Count', 'Token', 'Token Count'],
      rows: [['', '', '', '', '7', '', '42']],
    });
  });

  it('exports live input and select values instead of their initial markup values', () => {
    document.body.innerHTML = '<table><thead><tr><th>OID</th><th>模式</th></tr></thead><tbody><tr><td><input value="1.3.6.1"></td><td><select><option selected>直接百分比</option><option>已用/总量</option></select></td></tr></tbody></table>';
    document.querySelector<HTMLInputElement>('input')!.value = '1.3.6.1.4.1.9';
    document.querySelector<HTMLSelectElement>('select')!.value = '已用/总量';
    expect(readVisibleTableData(document.querySelector('table')!)).toEqual({
      headers: ['OID', '模式'],
      rows: [['1.3.6.1.4.1.9', '已用/总量']],
    });
  });

  it('applies the same rules to explicit CSS-grid data without changing visible order', () => {
    expect(readExplicitTableData({
      headers: ['名称', '资产 ID', '状态', 'SNMP Community', '操作'],
      rows: [['核心交换机', 'asset-123', '在线', 'community-secret', '编辑']],
    })).toEqual({
      headers: ['名称', '状态', 'SNMP Community'],
      rows: [['核心交换机', '在线', '']],
    });
  });

  it('writes UTF-8 CSV with quoting and formula-injection protection', () => {
    expect(serializeTableCsv(['名称', '备注'], [['核心,设备', '=HYPERLINK("x")']])).toBe('\uFEFF"名称","备注"\r\n"核心,设备","\'=HYPERLINK(""x"")"');
  });
});
