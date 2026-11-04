(() => {
  'use strict';

  const REPORT_ID_CONFIG = 0x10;
  const REPORT_ID_APP_COMMAND = 0x11;
  const APP_COMMAND_CONFIG_ACK = 0x03;
  const APP_COMMAND_HOST_ACTION = 0x05;
  const CONFIG_CHUNK_BYTES = 52;
  const REPORT_PAYLOAD_BYTES = 63;

  function crc16Ccitt(bytes) {
    let crc = 0xffff;
    for (const value of bytes) {
      crc ^= value << 8;
      for (let bit = 0; bit < 8; bit += 1) {
        crc = crc & 0x8000 ? ((crc << 1) ^ 0x1021) & 0xffff : (crc << 1) & 0xffff;
      }
    }
    return crc;
  }

  class BabyTapEasyInput {
    constructor(manifest, callbacks = {}) {
      this.manifest = manifest;
      this.callbacks = callbacks;
      this.device = null;
      this.uuidToKey = Object.fromEntries(
        Object.entries(manifest.key_actions || {}).map(([key, uuid]) => [uuid, Number(key)])
      );
      this._boundInput = event => this._handleInput(event);
      this._boundDisconnect = event => {
        if (this.device && event.device === this.device) this._setDevice(null, '键盘已断开');
      };
      if (this.supported) navigator.hid.addEventListener('disconnect', this._boundDisconnect);
    }

    get supported() {
      return typeof navigator !== 'undefined' && Boolean(navigator.hid);
    }

    get connected() {
      return Boolean(this.device && this.device.opened);
    }

    async connectGranted() {
      if (!this.supported) {
        this._state('unsupported', '当前浏览器不支持 WebHID');
        return false;
      }
      const devices = await navigator.hid.getDevices();
      const match = devices.find(device => this._matches(device));
      if (!match) {
        this._state('idle', '等待连接 EasyInput');
        return false;
      }
      return this._open(match);
    }

    async requestAndConnect() {
      if (!this.supported) throw new Error('当前浏览器不支持 WebHID，请使用 Chrome 或 Edge 打开本页');
      const devices = await navigator.hid.requestDevice({filters: [{
        vendorId: this.manifest.vendor_id,
        productId: this.manifest.product_id,
        usagePage: this.manifest.usage_page,
        usage: this.manifest.usage,
      }]});
      if (!devices.length) return false;
      return this._open(devices[0]);
    }

    async _open(device) {
      if (!device.opened) await device.open();
      device.removeEventListener('inputreport', this._boundInput);
      device.addEventListener('inputreport', this._boundInput);
      this._setDevice(device, 'EasyInput 已连接');
      return true;
    }

    _matches(device) {
      return device.vendorId === this.manifest.vendor_id && device.productId === this.manifest.product_id;
    }

    _setDevice(device, detail) {
      this.device = device;
      this._state(device ? 'connected' : 'idle', detail);
    }

    _state(state, detail) {
      if (this.callbacks.onState) this.callbacks.onState({state, detail, connected: this.connected});
    }

    _handleInput(event) {
      if (event.reportId !== REPORT_ID_APP_COMMAND) return;
      const bytes = new Uint8Array(event.data.buffer, event.data.byteOffset, event.data.byteLength);
      if (bytes.length < 4) return;
      const [kind, chunkIndex, totalChunks, dataLength] = bytes;
      if (chunkIndex !== 0 || totalChunks !== 1 || dataLength > 59 || bytes.length < 4 + dataLength) return;
      const data = bytes.slice(4, 4 + dataLength);
      if (kind === APP_COMMAND_HOST_ACTION && dataLength === 36) {
        const uuid = new TextDecoder('ascii').decode(data);
        const key = this.uuidToKey[uuid];
        if (key && this.callbacks.onKey) this.callbacks.onKey(key);
      }
      if (kind === APP_COMMAND_CONFIG_ACK && dataLength === 7 && this.callbacks.onConfigAck) {
        this.callbacks.onConfigAck({
          phase: data[0],
          ok: data[1] === 1,
          byteCount: data[2] | (data[3] << 8),
          crc16: data[4] | (data[5] << 8),
          saved: data[6] === 1,
        });
      }
    }

    async replaceConfig(config) {
      if (!this.connected) throw new Error('请先连接 EasyInput');
      const raw = new TextEncoder().encode(JSON.stringify(config));
      if (!raw.length || raw.length > 2048) throw new Error('配置大小必须在 1–2048 字节之间');
      const totalChunks = Math.ceil(raw.length / CONFIG_CHUNK_BYTES);
      const checksum = crc16Ccitt(raw);
      for (let index = 0; index < totalChunks; index += 1) {
        const chunk = raw.slice(index * CONFIG_CHUNK_BYTES, (index + 1) * CONFIG_CHUNK_BYTES);
        const payload = new Uint8Array(REPORT_PAYLOAD_BYTES);
        payload.set([0x53, 0x33, 0x43, 0x01], 0);
        payload[4] = index;
        payload[5] = totalChunks;
        payload[6] = raw.length & 0xff;
        payload[7] = (raw.length >> 8) & 0xff;
        payload[8] = chunk.length;
        payload[9] = checksum & 0xff;
        payload[10] = (checksum >> 8) & 0xff;
        payload.set(chunk, 11);
        await this.device.sendFeatureReport(REPORT_ID_CONFIG, payload);
      }
      return {byteCount: raw.length, crc16: checksum, chunks: totalChunks};
    }
  }

  window.BabyTapEasyInput = BabyTapEasyInput;
})();
