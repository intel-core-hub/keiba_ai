def input_result(engine, decisions):

    for d in decisions:

        r = input(f"{d.selection} HIT? 1/0:")

        hit = r == "1"

        profit = engine.update_result(d, hit)

        print("profit:", profit)