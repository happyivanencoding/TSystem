import pandas as pd
import pickle
import sys

def save_mapping(file,strat_file_path,preprocessing_file_path):
    xl = pd.ExcelFile(file)
    strat_ML = xl.parse('Mapping_strat_ML', header=[0,1])
    preprocessing_df = xl.parse('Mapping_preprocessing', header=[0,1])

    unique_strat = list(strat_ML.columns.get_level_values(0).unique())
    dict_strat = {}
    for strat in unique_strat:
        dict_strat[strat] = {col: ((strat_ML[strat][col].dropna().values)[0] if len(list(strat_ML[strat][col].dropna().values))==1 else list(strat_ML[strat][col].dropna().values)) for col in strat_ML[strat].columns}

    unique_preprocessing = list(preprocessing_df.columns.get_level_values(0).unique())
    dict_preprocessing = {}
    for preprocessing in unique_preprocessing:
        dict_preprocessing[preprocessing] = {col: ((preprocessing_df[preprocessing][col].dropna().values)[0] if len(list(preprocessing_df[preprocessing][col].dropna().values))==1 else list(preprocessing_df[preprocessing][col].dropna().values)) for col in preprocessing_df[preprocessing].columns}

    file = open(strat_file_path, 'wb')
    pickle.dump(dict_strat, file)
    file.close()
    file = open(preprocessing_file_path, 'wb')
    pickle.dump(dict_preprocessing, file)
    file.close()

if __name__=='__main__':
    launcher_file = sys.argv[1]
    strat_file_path = sys.argv[2]
    preprocessing_file_path = sys.argv[3]
    save_mapping(launcher_file,strat_file_path,preprocessing_file_path)