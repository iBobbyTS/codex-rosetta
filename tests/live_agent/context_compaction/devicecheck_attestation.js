#!/usr/bin/env node
"use strict";

const crypto = require("node:crypto");
const readline = require("node:readline");

const addonPath =
  process.env.CODEX_DEVICECHECK_ADDON ||
  "/Applications/ChatGPT.app/Contents/Resources/native/devicecheck.node";
const bundleIdentifier = process.env.CODEX_DESKTOP_BUNDLE_ID || "com.openai.codex";
const addon = require(addonPath);
const appSessionId = crypto.randomUUID();

function cborHead(major, value) {
  if (!Number.isSafeInteger(value) || value < 0) {
    throw new Error(`invalid CBOR unsigned integer: ${value}`);
  }
  if (value < 24) return Buffer.from([major + value]);
  if (value <= 0xff) return Buffer.from([major + 24, value]);
  if (value <= 0xffff) {
    const result = Buffer.allocUnsafe(3);
    result[0] = major + 25;
    result.writeUInt16BE(value, 1);
    return result;
  }
  if (value <= 0xffffffff) {
    const result = Buffer.allocUnsafe(5);
    result[0] = major + 26;
    result.writeUInt32BE(value, 1);
    return result;
  }
  throw new Error(`CBOR value is too large: ${value}`);
}

function cborText(value) {
  const encoded = Buffer.from(value, "utf8");
  return Buffer.concat([cborHead(0x60, encoded.length), encoded]);
}

function cborUnsigned(value) {
  return cborHead(0, value);
}

function cborFloat(value) {
  const result = Buffer.allocUnsafe(9);
  result[0] = 0xfb;
  result.writeDoubleBE(value, 1);
  return result;
}

function cborArray(values) {
  return Buffer.concat([cborHead(0x80, values.length), ...values]);
}

function cborMap(entries) {
  return Buffer.concat([
    cborHead(0xa0, entries.length),
    ...entries.flatMap(([key, value]) => [key, value]),
  ]);
}

function desktopSignals() {
  const locale = Intl.DateTimeFormat().resolvedOptions().locale || "unknown";
  const timezone =
    Intl.DateTimeFormat().resolvedOptions().timeZone || "unknown";
  return {
    schemaVersion: 1,
    preferredLanguages: [locale],
    locale,
    timezone,
    screenSizeSum: 0,
    screenScale: 1,
    appSessionId,
  };
}

function encodeSignals(signals) {
  const fields = cborMap([
    [cborUnsigned(0), cborUnsigned(signals.schemaVersion)],
    [cborUnsigned(1), cborArray(signals.preferredLanguages.map(cborText))],
    [cborUnsigned(2), cborText(signals.locale)],
    [cborUnsigned(3), cborText(signals.timezone)],
    [cborUnsigned(4), cborUnsigned(signals.screenSizeSum)],
    [cborUnsigned(5), cborFloat(signals.screenScale)],
    [cborUnsigned(6), cborText(signals.appSessionId)],
  ]);
  return [cborText("f"), fields];
}

function encodeDesktopToken(deviceCheck) {
  const entries = [
    [cborText("token"), cborText(deviceCheck.tokenBase64)],
    [cborText("bundle_id"), cborText(bundleIdentifier)],
    encodeSignals(desktopSignals()),
  ];
  if (deviceCheck.latencyMs != null) {
    entries.push([cborText("t"), cborFloat(deviceCheck.latencyMs)]);
  }
  return `v1.${cborMap(entries).toString("base64url")}`;
}

async function generate() {
  const result = await addon.generateToken();
  if (!result.supported || typeof result.tokenBase64 !== "string") {
    throw new Error("DeviceCheck attestation is unavailable");
  }
  return encodeDesktopToken(result);
}

const lines = readline.createInterface({ input: process.stdin });
process.stdout.write('{"ready":true}\n');
lines.on("line", async () => {
  try {
    const token = await generate();
    process.stdout.write(`${JSON.stringify({ token })}\n`);
  } catch (error) {
    process.stdout.write(`${JSON.stringify({ error: String(error) })}\n`);
  }
});
