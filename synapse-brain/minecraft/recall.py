"""
Recall: remembering what I have read, when my own experience is not enough.

The game's reference book (knowledge/: which tool every block needs and what it drops, every recipe) is
something Synapse has read. It is not a rule of behaviour - it says how the world works, not what to do.
He turns to it the way a person does, in two situations:

  surprise   - I broke a block and got nothing, again; and from my own life I know that breaking things
               usually gives something. "Stone... right, stone is mined with a pickaxe, then it drops cobblestone."
  not knowing how - I want a thing and my mind knows no way to it yet: "how is a wooden pickaxe made?"

What he recalls goes into the mind as a weak belief (mind.tell, like a book), which experience confirms
or overturns. Whether to make a pickaxe, and when, the mind still decides by its own values and plans.
"""
import json
import os

from personality import RU_NAMES

HERE = os.path.dirname(os.path.abspath(__file__))


BLOCKS_RU = {"stone": "камень", "cobblestone": "булыжник", "deepslate": "глубинный сланец", "coal_ore": "угольную руду",
             "iron_ore": "железную руду", "copper_ore": "медную руду", "gold_ore": "золотую руду",
             "diamond_ore": "алмазную руду", "redstone_ore": "редстоуновую руду", "lapis_ore": "лазуритовую руду",
             "obsidian": "обсидиан", "raw_iron": "сырое железо", "coal": "уголь", "diamond": "алмаз"}


def ru(name):
    return RU_NAMES.get(name) or BLOCKS_RU.get(name) or name.replace("_", " ")


def recolor(ingredient, item):
    """The same kind of thing in another colour (black_bed for white_bed): a re-dyeing recipe."""
    return ingredient != item and "_" in item and ingredient.rsplit("_", 1)[-1] == item.rsplit("_", 1)[-1]


class Recall:
    def __init__(self, knowledge=os.path.join(HERE, "knowledge", "sim_rules.json")):
        self.ok = os.path.exists(knowledge)
        rules = json.load(open(knowledge, encoding="utf-8")) if self.ok else {}
        self.blocks, self.recipes = rules.get("blocks", {}), rules.get("recipes", {})
        self.breaks = {}               # block -> [times broken, times it gave something]
        self.total = [0, 0]            # all my breaking, and how often it gave me something
        self.recalled = set()          # what I have already recalled about (once is enough: then experience)
        self.looked = {}               # wanted thing -> my age when I last tried to remember how

    # ---------------------------------------------------------------- the two occasions
    def moment(self, m, child):
        """Returns what I realised this moment (words for the diary and the chat), or None."""
        if not self.ok:
            return None
        said = None
        for block, gained in (m.get("fev") or {}).get("broke", []):
            st = self.breaks.setdefault(block, [0, 0])
            st[0] += 1
            self.total[0] += 1
            if gained:
                st[1] += 1
                self.total[1] += 1
                continue
            usually = self.total[1] / max(1, self.total[0])           # learned from my own life, not given
            if st[0] >= 2 and st[1] == 0 and usually >= 0.5 and ("block", block) not in self.recalled:
                said = self.about_block(block, child) or said
        mind = child.mind
        g = getattr(mind, "goal", None)
        if g is not None and g < len(mind.names):
            want = mind.names[g]
            if want.startswith("have:") and len(mind.pre(g)) == 0 and ("item", want[5:]) not in self.recalled \
                    and child.age - self.looked.get(want, -10 ** 9) > 2000:
                self.looked[want] = child.age
                said = self.about_item(want[5:], child) or said
        return said

    # ---------------------------------------------------------------- what the reference says
    def about_block(self, block, child):
        info = self.blocks.get(block)
        self.recalled.add(("block", block))
        if not info or not info.get("drops"):
            return f"Сломал {ru(block)} — ничего не выпало. Не помню, как его добывают."
        drop, tools = info["drops"][0], info.get("tools") or []
        if not tools:
            return None                                                # nothing needed: it was something else
        claims = [("have:" + drop, ["have:" + tools[0], "see:" + block])]
        child.mind.tell(claims, {}, source="справочник")
        return (f"Сломал {ru(block)} — ничего не выпало. Вспомнил из справочника: {ru(block)} добывают "
                f"инструментом ({ru(tools[0])} или лучше), тогда выпадет {ru(drop)}.")

    def about_item(self, item, child):
        self.recalled.add(("item", item))
        # a recipe that only unpacks a storage block (9 raw iron from a block of raw iron) says nothing about
        # where the thing comes from: then remember where it is mined instead
        rs = [r for r in self.recipes.get(item, []) if not (len(r["need"]) == 1 and r.get("makes", 1) >= 9
                                                             and next(iter(r["need"])).endswith("_block"))]
        # nor does re-dyeing (a white bed from a black bed and white dye): how the thing is first made comes first
        rs.sort(key=lambda r: any(recolor(k, item) for k in r["need"]))
        if rs:
            r = rs[0]
            pres = ["have:" + k for k in r["need"]] + (["at_table"] if r.get("table") else [])   # a table at hand:
            claims = [("have:" + item, pres)]                                                  # in my bag or near
            if r.get("table"):
                claims.append(("at_table", ["have:crafting_table"]))      # (my own table is one I can always set down)
            child.mind.tell(claims, {}, source="справочник")
            need = ", ".join(f"{n} {ru(k)}" for k, n in r["need"].items())
            return f"Хочу {ru(item)}. Вспомнил рецепт: {need}" + (", на верстаке." if r.get("table") else ".")
        sources = [(b, v.get("tools") or []) for b, v in self.blocks.items() if item in (v.get("drops") or []) and b != item
                   and not b.startswith(("potted_", "infested_"))]                  # from nature, not from a flower pot
        if not sources:
            return None
        block, tools = min(sources, key=lambda s: 0 if not s[1] else 1)     # prefer what needs no tool
        pres = ["see:" + block] + (["have:" + tools[0]] if tools else [])
        child.mind.tell([("have:" + item, pres)], {}, source="справочник")
        how = f" инструментом ({ru(tools[0])} или лучше)" if tools else ""
        return f"Хочу {ru(item)}. Вспомнил: это добывают из блока «{ru(block)}»{how}."
