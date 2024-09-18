from collections import defaultdict

int2on_off_dict= defaultdict(lambda:"unknown", {0:"off", 1:"on"})

def int2on_off(i):
    return int2on_off_dict[i]

def divideby10(i):
    return float(i)/10

def mv2v(i):
    volts = float(i)*.001
    return f"{volts:.3f}"

def floatnegation(i):
    # We don't want a negative sign on 0
    current = 0.0 if i == 0.0 else -i
    return f"{current:.2f}"

def float2decimals(i):
    #just return the number with 2 decimal places
    return f"{i:.2f}"

