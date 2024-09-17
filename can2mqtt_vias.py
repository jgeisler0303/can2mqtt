from collections import defaultdict

int2on_off_dict= defaultdict(lambda:"unknown", {0:"off", 1:"on"})

def int2on_off(i):
    return int2on_off_dict[i]

def divideby10(i):
    return float(i)/10
