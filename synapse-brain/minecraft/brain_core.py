"""
One moment of the grown brain: the body's report in, a motor command out.

Shared by the Minecraft server (brain_server.py) and the simulated world (../agent/minesim.py),
so that what the brain learns in one is the same brain, in the same code, in the other.
"""
import time

import feel_bridge
from mind_bridge import talk as mind_talk


class Grown:
    def __init__(self, child, me=None, voice=None, log=print):
        self.child, self.me, self.voice, self.log = child, me, voice, log
        self.body = feel_bridge.Body()
        self.a_prev, self.front_prev, self.inv_prev, self.last_felt = None, 0, {}, 0.0
        self.clock = time.time

    def new_body(self):
        """Reconnected: the senses start again (the brain and memory stay)."""
        self.body = feel_bridge.Body()
        self.a_prev, self.front_prev, self.inv_prev = None, 0, {}

    def decide(self, m, frame=None, force=None):
        child, me = self.child, self.me
        say, reward = None, float(m.get("reward", 0.0))
        if me:                                                # the reward comes from inside
            reward, say = me.feel(m)
        for user, text in m.get("heard", []):                 # someone spoke to us
            if not say:
                say = feel_bridge.talk(child, text)
            if not say:
                say = mind_talk(child.mind, text)
            if self.voice and not say:
                say = self.voice.reply(text, me)
            if me:
                me.note(f"{user} сказал: «{text}»" + (f"; я ответил: «{say}»" if say else ""), None)
        o = self.body.to_o(m, self.a_prev, frame)
        child.m = m
        a = child.step(o, self.a_prev, self.front_prev, self.inv_prev, extra_reward=reward)
        if force is not None:
            a = force                                         # the experimenter's hand, felt as its own movement
        self.a_prev, self.front_prev, self.inv_prev = a, int(o["view"][7]), dict(o["inv"])
        fev = m.get("fev") or {}
        if fev.get("read"):                                   # reading: text -> beliefs in the mind
            from reading import read as parse_text, MC_NAMES
            claims, values = parse_text(fev["read"], MC_NAMES)
            child.mind.tell(claims, values)
            self.log(f"[read] {fev['read'][:80]}... -> {claims} {values}")
            if me:
                me.note(f"прочитал книгу: «{fev['read'][:120]}»; поверил: " + "; ".join(
                    f"{t} ← {' + '.join(p)}" for t, p in claims), None)
        L = child.limbic
        if max(L.e.values()) > 0.6 and self.clock() - self.last_felt > 90:
            self.last_felt = self.clock()
            felt = L.say()
            if me:
                me.note("чувствую: " + felt, None)
            say = say or felt
        return a, feel_bridge.attention(child, a, m), say, o
