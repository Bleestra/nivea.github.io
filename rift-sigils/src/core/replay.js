// ReplayLog (§20): rules version + content hash + initial setup + accepted commands reproduce the match exactly.
import { CONTENT_HASH, RULES_VERSION } from './content.js';
import { apply, createMatch, MatchError } from './engine.js';
import { hashString } from './rng.js';

export function newRecord(setup) {
  const { state } = createMatch(setup);
  return { record: { rulesVersion: RULES_VERSION, contentHash: CONTENT_HASH, setup, commands: [] }, state };
}

// Applies a command and appends it to the record only if the engine accepted it.
export function applyRecorded(record, state, cmd) {
  const r = apply(state, cmd);
  if (r.ok) record.commands.push(cmd);
  return r;
}

export function replay(record) {
  if (record.rulesVersion !== RULES_VERSION || record.contentHash !== CONTENT_HASH) {
    throw new MatchError('content-mismatch', `запись ${record.contentHash}, движок ${CONTENT_HASH}`);
  }
  let { state } = createMatch(record.setup);
  for (const cmd of record.commands) {
    const r = apply(state, cmd);
    if (!r.ok) throw new MatchError('replay-diverged', r.error);
    state = r.state;
  }
  return state;
}

export const stateHash = s => hashString(JSON.stringify(s));
