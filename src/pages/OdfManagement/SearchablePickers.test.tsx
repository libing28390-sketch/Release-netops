import React from 'react';
import { act, fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import {
  DeviceOption,
  InterfaceOption,
  SearchableDevicePicker,
  SearchableInterfacePicker,
} from './SearchablePickers';

const SAMPLE_DEVICES: DeviceOption[] = [
  { id: 'd1', hostname: 'S6850_1', ip_address: '10.254.0.1', vendor: 'H3C', model: 'S6850', rack_name: 'J-01' },
  { id: 'd2', hostname: 'F1090-9', ip_address: '192.168.56.11', vendor: 'H3C', model: 'F1090', rack_name: 'J-01' },
  { id: 'd3', hostname: 'AC_11', ip_address: '192.168.56.14', vendor: 'Ruijie', model: 'WS6008', rack_name: 'J-02' },
];

const SAMPLE_INTERFACES: InterfaceOption[] = [
  { interface_name: 'Ten-GigabitEthernet1/0/49', oper_status: 'up', description: 'Core Uplink' },
  { interface_name: 'FortyGigE1/0/53', oper_status: 'down', description: 'Spine Stack' },
];

describe('SearchableDevicePicker', () => {
  it('filters local devices by hostname, IP, model, or rack and triggers debounced remote search', async () => {
    vi.useFakeTimers();
    const remoteDevice: DeviceOption = {
      id: 'd99',
      hostname: 'CORE-ZTE-9904',
      ip_address: '10.99.0.1',
      vendor: 'ZTE',
      model: 'ZXR10',
      rack_name: 'JG-01',
    };
    const onSearchRemote = vi.fn().mockResolvedValue([remoteDevice]);
    const onSelect = vi.fn();

    render(
      <SearchableDevicePicker
        valueId=""
        valueName=""
        initialDevices={SAMPLE_DEVICES}
        onSearchRemote={onSearchRemote}
        onSelect={onSelect}
        zh
      />,
    );

    const input = screen.getByLabelText('搜索 CMDB 网络设备');
    fireEvent.focus(input);

    // Initially displays all local devices
    expect(screen.getByText('S6850_1')).toBeTruthy();
    expect(screen.getByText('F1090-9')).toBeTruthy();

    // Local filter by rack name J-02 narrows list cleanly
    fireEvent.change(input, { target: { value: 'J-02' } });
    expect(screen.getByText('AC_11')).toBeTruthy();
    expect(screen.queryByText('S6850_1')).toBeNull();

    // Typing remote query fires debounced backend search and merges remote hits
    fireEvent.change(input, { target: { value: 'ZXR10' } });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(250);
    });
    expect(onSearchRemote).toHaveBeenCalledWith('ZXR10');
    expect(screen.getByText('CORE-ZTE-9904')).toBeTruthy();

    fireEvent.mouseDown(screen.getByText('CORE-ZTE-9904'));
    expect(onSelect).toHaveBeenCalledWith(remoteDevice);
    vi.useRealTimers();
  });
});

describe('SearchableInterfacePicker', () => {
  it('filters discovered interfaces and allows typing custom interface names', () => {
    const onChange = vi.fn();
    render(
      <SearchableInterfacePicker
        value=""
        options={SAMPLE_INTERFACES}
        onChange={onChange}
        zh
      />,
    );

    const input = screen.getByLabelText('搜索物理接口');
    fireEvent.focus(input);
    expect(screen.getByText('Ten-GigabitEthernet1/0/49')).toBeTruthy();
    expect(screen.getByText('FortyGigE1/0/53')).toBeTruthy();

    fireEvent.mouseDown(screen.getByText('Ten-GigabitEthernet1/0/49'));
    expect(onChange).toHaveBeenCalledWith('Ten-GigabitEthernet1/0/49');

    fireEvent.change(input, { target: { value: 'HundredGigE1/0/1' } });
    expect(onChange).toHaveBeenCalledWith('HundredGigE1/0/1');
  });
});
