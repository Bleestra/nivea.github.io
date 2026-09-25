"""
Self: intrinsic motivation, drives and an autobiographical memory for the Minecraft brain.

Nobody tells the agent what is good. Its reward comes from inside, like an animal's:
  novelty    - the first time it ever holds an item type (+1); getting more of something it already
               knows is worth little (habituation: +0.05)
  places     - entering a region (chunk) it has never been in (+0.2): place cells / exploration drive
  hunger     - the hypothalamus: an empty stomach hurts a little every step, eating when hungry is
               a relief
  pain       - losing health (-1), handled together with the amygdala's fear
Its life story is kept in `self.json` (identity: name, age, what it knows, where it has been)
and in a diary, and it speaks about its discoveries in the game chat.
"""
import json
import os
import time

RU_NAMES = {"oak_log": "дубовое бревно", "birch_log": "берёзовое бревно", "spruce_log": "еловое бревно",
            "oak_planks": "дубовые доски", "birch_planks": "берёзовые доски", "spruce_planks": "еловые доски",
            "stick": "палки", "crafting_table": "верстак", "wooden_pickaxe": "деревянную кирку",
            "cobblestone": "булыжник", "dirt": "землю", "stone_pickaxe": "каменную кирку",
            "wooden_axe": "деревянный топор", "wooden_shovel": "деревянную лопату", "coal": "уголь",
            "torch": "факелы", "sand": "песок", "gravel": "гравий", "flint": "кремень",
            "diamond": "алмаз", "diamond_pickaxe": "алмазную кирку", "iron_pickaxe": "железную кирку",
            "iron_ingot": "железный слиток", "raw_iron": "железную руду", "emerald": "изумруд",
            "written_book": "книгу", "oak_door": "дубовую дверь",
            "wheat_seeds": "семена пшеницы", "apple": "яблоко", "furnace": "печь"}


class Self:
    def __init__(self, path, name="Синапс"):
        self.path = path
        self.me = {"name": name, "born": time.strftime("%Y-%m-%d %H:%M"), "age_steps": 0,
                   "known_items": {}, "places": [], "discoveries": []}
        if os.path.exists(path):
            with open(path) as f:
                self.me.update(json.load(f))
        self.places = set(map(tuple, self.me["places"]))
        self.prev_items, self.prev_food, self.prev_health = None, 20, 20
        self.since_joy = 0  # steps since anything pleasant happened
        self.this_life = set()  # what I have had since I was last born
        self.diary = os.path.splitext(path)[0] + "_diary.md"

    def feel(self, m):
        """m: the body's report (items, chunk, food, health). Returns (intrinsic reward, speech)."""
        self.me["age_steps"] += 1
        if self.me["age_steps"] % 100 == 0:
            self.save()
        items = m.get("items", {})
        r, say = -0.01, None
        self.novelty_now = 0.0                        # the joy of a discovery this moment (not the thing's own worth)
        # novelty and habituation
        if self.prev_items is not None:
            for k, n in items.items():
                gain = n - self.prev_items.get(k, 0)
                if gain <= 0:
                    continue
                if k not in self.me["known_items"]:
                    r += 1.0
                    self.novelty_now += 1.0
                    say = self.discover(k)
                elif k not in self.this_life:
                    r += 0.3                  # getting back what I had lost: satisfaction of rebuilding
                else:
                    r += 0.05 * min(gain, 4)
                self.this_life.add(k)
                self.me["known_items"][k] = self.me["known_items"].get(k, 0) + gain
        self.prev_items = dict(items)
        # exploration of places
        ch = tuple(m.get("chunk", (0, 0)))
        if ch not in self.places:
            self.places.add(ch)
            r += 0.2
        # hunger and pain
        food, hp = m.get("food", 20), m.get("health", 20)
        if food < 10:
            r -= 0.02
        if food > self.prev_food and self.prev_food < 18:
            r += 0.5
        if hp < self.prev_health:
            r -= 1.0
        for adv_id, title in m.get("advancements", []):  # an advancement: a big, lasting joy
            if adv_id not in self.me.setdefault("advancements", []):
                self.me["advancements"].append(adv_id)
                r += 2.0
                say = self.note(f"получил достижение «{title}»", f"Ура! Достижение «{title}»! "
                                f"Это уже {len(self.me['advancements'])}-е.")
        if m.get("died"):
            say = self.remember_death(m["died"])
            self.this_life = set()
        self.prev_food, self.prev_health = food, hp
        self.since_joy = 0 if r > 0.05 else self.since_joy + 1
        return r, say

    def exploration(self):
        """Young and bored -> explore more: curiosity of youth fades with age (steps lived since
        birth, not inherited experience); boredom grows when nothing pleasant happens."""
        youth = 0.3 * 0.5 ** (self.me["age_steps"] / 3000)
        boredom = min(0.35, self.since_joy / 400 * 0.35)
        return max(0.05, youth, boredom)

    def discover(self, item):
        name = RU_NAMES.get(item, item.replace("_", " "))
        entry = {"step": self.me["age_steps"], "item": item, "time": time.strftime("%H:%M:%S")}
        self.me["discoveries"].append(entry)
        n = len(self.me["discoveries"])
        with open(self.diary, "a", encoding="utf-8") as f:
            f.write(f"- шаг {entry['step']} ({entry['time']}): впервые получил {name} — открытие №{n}\n")
        self.save()  # a discovery is never forgotten
        return f"Я впервые получил {name}! Это моё открытие №{n}."

    def note(self, what, speech):
        with open(self.diary, "a", encoding="utf-8") as f:
            f.write(f"- шаг {self.me['age_steps']} ({time.strftime('%H:%M:%S')}): {what}\n")
        self.save()
        return speech

    def remember_death(self, cause):
        ru = {"drowned": "утонул", "fell from a high place": "упал с высоты", "burned to death": "сгорел",
              "tried to swim in lava": "попал в лаву", "suffocated in a wall": "задохнулся в стене",
              "starved to death": "умер от голода"}.get(cause, cause)
        self.me.setdefault("deaths", []).append({"step": self.me["age_steps"], "cause": cause})
        with open(self.diary, "a", encoding="utf-8") as f:
            f.write(f"- шаг {self.me['age_steps']} ({time.strftime('%H:%M:%S')}): погиб — {ru}. Всё, что было в руках, "
                    f"потеряно, но знания остались со мной.\n")
        self.prev_items = {}
        self.save()
        return f"Я {ru}... Запомню это. Начинаю заново, но знаю уже {len(self.me['known_items'])} вещей."

    def save(self):
        self.me["places"] = sorted(self.places)
        with open(self.path, "w") as f:
            json.dump(self.me, f, ensure_ascii=False, indent=1)

    def drives(self, m):
        """Internal state as extra senses for the brain (hunger level, what it could still discover)."""
        food = m.get("food", 20)
        return ([min(food // 5, 4), int(bool(m.get("can_craft_new"))), min(len(self.me["known_items"]), 15)]
                + list(m.get("feat", [])))
