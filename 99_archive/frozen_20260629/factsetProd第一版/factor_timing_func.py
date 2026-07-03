import numpy as np
from scipy.stats import rankdata
from pyxll import xl_func

@xl_func("int[] histo_val, int[] rank: numpy_row<int>")
def get_rank(histo_val, rank):

    histo_val = np.array(histo_val)
    rank = np.array(rank)
    rank_occur = np.unique(rank, return_counts=True)
    doublons = np.where(rank_occur[1]>1)[0]
    for doublon in doublons:
        index_doublon = np.where(rank == rank_occur[0][doublon])[0]
        histo_doublon = histo_val[index_doublon]
        new_rank = rankdata(histo_doublon, method='max') -1 
        new_rank = np.abs(new_rank - np.max(new_rank))
        rank[index_doublon] += new_rank
    return rank.reshape(len(rank),1)


    # alpha = 0.5

    # histo_val = np.array(histo_val)
    # rank = np.array(rank)
    # rank_occur = np.unique(rank, return_counts=True)
    # doublons = np.where(rank_occur[1] > 1)[0]

    # for doublon in doublons:
    #     index_doublon = np.where(rank == rank_occur[0][doublon])[0]
    #     histo_doublon = histo_val[index_doublon]

    #     # Historical Rank Calculation
    #     new_rank = rankdata(histo_doublon, method='max') - 1
    #     new_rank = np.abs(new_rank - np.max(new_rank))

    #     # Combine Rank with Weight
    #     final_rank = alpha * new_rank + (1 - alpha) * np.arange(len(index_doublon))

    #     # Rank again to ensure order
    #     final_rank = rankdata(final_rank, method='ordinal') - 1
    #     rank[index_doublon] += final_rank

    # return rank.reshape(len(rank), 1)


@xl_func("int[] score_quali, int[] score_quanti, int[] score_quali_inv, str type, int exclusion: numpy_row<int>")
def tab_invest(score_quali, score_quanti, score_quali_inv, type, exclusion):

    score_quali = np.array(score_quali)
    score_quali_inv = np.array(score_quali_inv)
    score_quanti = np.array(score_quanti)
    flag_final = np.zeros(len(score_quali), dtype=int)

    if type ==  "Top":
        score_final = score_quali + score_quanti/20
    else:
        score_final = score_quali + 1/(score_quanti+1)
    index_exclusion = np.where(score_quali_inv >= exclusion)[0]
    score_final[index_exclusion] = 0
    rang_final = rankdata(score_final, method='min')
    flag_final[np.where(rang_final>9)[0]] = 1

    return flag_final

@xl_func("int[] score_quali, int[] score_quanti, int[] score_quali_inv, str type, int exclusion: numpy_row<int>")
def tab_invest_eu(score_quali, score_quanti, score_quali_inv, type, exclusion):

    score_quali = np.array(score_quali)
    score_quali_inv = np.array(score_quali_inv)
    score_quanti = np.array(score_quanti)
    flag_final = np.zeros(len(score_quali), dtype=int)

    if type ==  "Top":
        score_final = score_quali + score_quanti/20
    else:
        score_final = score_quali + 1/(score_quanti+1)
    index_exclusion = np.where(score_quali_inv >= exclusion)[0]
    score_final[index_exclusion] = 0
    rang_final = rankdata(score_final, method='min')
    flag_final[np.where(rang_final>10)[0]] = 1

    return flag_final


@xl_func("int[] score_quali: int")
def tab_invest_test(score_quali):

    return score_quali[0]
        
if __name__ == '__main__':
    histo_val = [5,13,5,5,8,12]
    rank = [2,1,2,5,2,5]
    a = get_rank(histo_val, rank)
    print(a.reshape(len(a),1))
