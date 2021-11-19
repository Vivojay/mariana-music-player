
songslist = [
    (0, 'Cloudless'),
    (1, 'Halloween_Rap'),
    (2, 'iamwhatiam'),
    (3, 'In My Room - TiaCorine Remix Nightcore'),
    (4, 'Jesse & The Wolf - Selecta REMIX'),
    (5, 'RickRoll becomes RitaRoll'),
    (6, 'RitaRoll (Old)'),
    (7, 'Still DRE Remake [Tribute]'),
    (8, 'WindowPane'),
    (9, '100 gecs - money machine (Official Music Video)'),
    (10, '8485 - 1_15'),
    (11, '8485 - 4 Real (feat. Petal Supply) (prod. Umru)'),
    (12, '8485 - so dark'),
    (13, '8_00'),
    (14, '97 gold infiniti - Emeryld (Official Visualizer)'),
    (15, 'A2 - Renegade (Official Video)'),
    (16, "Abby Jasmine - 'Stuck on You' (Official Music Video)"),
    (17, 'ABRA - Fruit (Official Music Video)'),
    (18, 'ABRA - Vegas (Audio)'),
    (19, 'Alex Mali - Control (Audio)'),
]



querylist = ['ale', 'mal', 'cont']

def search(songslist, querylist):
    out = []
    for index, song in songslist:
        is_in = []
        for query in querylist:
            if query in song:
                is_in.append(True)
            else:
                is_in.append(False)
                print('NOT FOUND IN', song)
                break
        
        if False not in is_in:
            out.append((index, song))

    return out

mysearch = search(songslist=songslist, querylist=querylist)

print(mysearch)


