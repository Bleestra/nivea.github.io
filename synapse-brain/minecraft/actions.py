"""The body's action repertoire, by number. The same list as ACTIONS in ../fabric-mod Motor.java; bot.js
has the first 41. Only names: HOW each is done is the body's; WHEN, the brain learns."""

ACTIONS = ["forward", "turn_left", "turn_right", "dig_front", "wait",
           "craft_new", "eat", "back", "strafe_left", "strafe_right", "jump", "toggle_sprint", "toggle_sneak",
           "look_up", "look_down", "attack", "use_item", "dig_down", "equip_armor", "equip_weapon",
           "equip_tool", "place_block", "craft_gear", "smelt", "sleep", "drop_junk", "pillar_up", "dig_up",
           "fish", "interact", "store", "take", "place_chest", "trade", "read",
           "approach", "mine_target", "craft_target", "goto_place", "explore", "place_frame",
           # what a player's hands do: the head a little, walking where I look, the mouse buttons on what is
           # under the crosshair, the hotbar keys, swap hands, drop
           "look_left_fine", "look_right_fine", "look_up_fine", "look_down_fine", "walk", "hit", "use", "hold_use",
           "hotbar_1", "hotbar_2", "hotbar_3", "hotbar_4", "hotbar_5", "hotbar_6", "hotbar_7", "hotbar_8", "hotbar_9",
           "swap_hands", "drop_item"]

RU = {"forward": "вперёд", "turn_left": "повернуть налево", "turn_right": "повернуть направо", "dig_front": "копать впереди",
      "wait": "ждать", "craft_new": "смастерить новое", "eat": "есть", "back": "назад", "strafe_left": "шаг влево",
      "strafe_right": "шаг вправо", "jump": "прыжок", "toggle_sprint": "бег вкл/выкл", "toggle_sneak": "присесть (Shift)",
      "look_up": "посмотреть вверх", "look_down": "посмотреть вниз", "attack": "ударить", "use_item": "использовать предмет",
      "dig_down": "копать вниз", "equip_armor": "надеть броню", "equip_weapon": "взять оружие", "equip_tool": "взять инструмент",
      "place_block": "поставить блок", "craft_gear": "смастерить снаряжение", "smelt": "переплавить", "sleep": "спать",
      "drop_junk": "выбросить вещь", "pillar_up": "подняться на блоке", "dig_up": "копать вверх", "fish": "рыбачить",
      "interact": "взаимодействовать", "store": "положить в сундук", "take": "взять из сундука", "place_chest": "поставить сундук",
      "trade": "торговать", "read": "читать", "approach": "подойти к", "mine_target": "добыть", "craft_target": "смастерить",
      "goto_place": "идти домой", "explore": "исследовать", "place_frame": "строить портал",
      "look_left_fine": "голову левее", "look_right_fine": "голову правее", "look_up_fine": "голову выше",
      "look_down_fine": "голову ниже", "walk": "идти, куда смотрю", "hit": "ЛКМ", "use": "ПКМ", "hold_use": "держать ПКМ",
      "swap_hands": "сменить руку (F)", "drop_item": "бросить (Q)"}
for _k in range(1, 10):
    RU[f"hotbar_{_k}"] = f"слот {_k}"


def ru(i):
    return RU.get(ACTIONS[i], ACTIONS[i]) if 0 <= i < len(ACTIONS) else str(i)
