import torch
import torch.nn as nn
import numpy as np
from sklearn.preprocessing import StandardScaler, MinMaxScaler, OneHotEncoder
from sklearn.compose import ColumnTransformer
from sklearn.impute import KNNImputer,SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.ensemble import RandomForestRegressor
from torch.optim.lr_scheduler import ReduceLROnPlateau 
from sklearn.linear_model import LogisticRegression
import scipy
import pandas as pd

import torch.nn.functional as F
from sklearn.metrics import accuracy_score, f1_score,mean_absolute_percentage_error,mean_squared_error,r2_score
from torch.utils.data import DataLoader, TensorDataset

device=torch.device('cuda' if torch.cuda.is_available() else 'cpu')


class MLPClassifier(nn.Module):
    def __init__(self, input_dim):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(input_dim, 128),
            nn.BatchNorm1d(128),
            nn.ReLU(),
            nn.Dropout(0.3),
            nn.Linear(128, 64),
            nn.ReLU(),
            nn.Linear(64, 1)  # 1 output → binary
        )

    def forward(self, x):
        return self.net(x) 

class NN(nn.Module):
    def __init__(
        self,
        input_dim,
        hidden_units_4,
        hidden_units_1=128,
        hidden_units_2=128,
        hidden_units_3=128,
        dropout_rate_1=0.2,
        dropout_rate_2=0.2,
        dropout_rate_3=0.2,
        activation_function_1=nn.ReLU(),
        activation_function_2=nn.ReLU(),
        activation_function_3=nn.ReLU(),
        activation_function_4=nn.Identity(),
    ):
        super(NN, self).__init__()

        # First Hidden Layer
        self.hidden1 = nn.Linear(input_dim, hidden_units_1)
        self.bn1 = nn.BatchNorm1d(hidden_units_1)
        self.act1 = activation_function_1
        self.drop1 = nn.Dropout(dropout_rate_1)

        # Second Hidden Layer
        self.hidden2 = nn.Linear(hidden_units_1, hidden_units_2)
        self.bn2 = nn.BatchNorm1d(hidden_units_2)
        self.act2 = activation_function_2
        self.drop2 = nn.Dropout(dropout_rate_2)

        # Third Hidden Layer
        self.hidden3 = nn.Linear(hidden_units_2, hidden_units_3)
        self.bn3 = nn.BatchNorm1d(hidden_units_3)
        self.act3 = activation_function_3
        self.drop3 = nn.Dropout(dropout_rate_3)
        
        # fourth Hidden Layer
        self.hidden4 = nn.Linear(hidden_units_3, hidden_units_4)
        self.act4 = activation_function_4

    def forward(self, x):
        x = self.hidden1(x)
        x = self.bn1(x)
        x = self.act1(x)
        x = self.drop1(x)
        # layer 2
        x = self.hidden2(x)
        x = self.bn2(x)
        x = self.act2(x)
        x = self.drop2(x)
        # layer 3
        x = self.hidden3(x)
        x = self.bn3(x)
        x = self.act3(x)
        x = self.drop3(x)
        # layer 4
        x = self.hidden4(x)
        x = self.act4(x)

        return x

class MLP:
    def __init__(self,input_dim,output_dim,parameters):
        self.input_dim=input_dim
        self.output_dim=output_dim
        self.parameters=parameters
        self.model=NN(self.input_dim, self.output_dim)
        self.preprocessing=None

    def fit(self,X_train,Y_train,epochs=100, batch_size=256, l1_lambda=0, l2_lambda=0.001, 
            loss_function = nn.BCEWithLogitsLoss(),learning_rate=0.1, to_print=True):
        
        """     
        Fonction pour entrainer le modèle NeuralNet

        Args:    
                
                X_train: variable explicative
                Y_train: target
                l1_lambda: coefficient de regularisation l1
                l2_lambda: coefficient de regularisation l2
                parameters: paramètres du réseau de neurones
                loss_function: fonction de loss à minimiser
                objective:  decide s'il faut entrainer le modèle en classification ou en régression
        
        return: le modèle entrainé et les loss à travers les différents epochs
        
        """
        if type(X_train)==pd.DataFrame:
            numerical_features=list(X_train.select_dtypes(exclude='object').columns)
            categorical_features=list(X_train.select_dtypes(include='object').columns)


            numerical_pipeline = Pipeline([
                ('imputer', SimpleImputer(strategy='mean')),
                ('scaler', MinMaxScaler())])

            categorical_pipeline = Pipeline([
                ('imputer', SimpleImputer(strategy='most_frequent')),
                ('scaler',  OneHotEncoder(handle_unknown='ignore', drop='first',
                        sparse_output=False,
                        dtype=int),)])

            preprocessor = ColumnTransformer(
                transformers=[
                    ('num', numerical_pipeline, numerical_features),
                    ('cat', categorical_pipeline, categorical_features),
                ])

            X_train=preprocessor.fit_transform(X_train)
            Y_train=Y_train.values.reshape(-1,1)
            self.preprocessing=preprocessor
        
        Y_train=(Y_train>0).astype(int)
        model=MLPClassifier(input_dim=self.input_dim)
        #if self.parameters is not None:
        #    model=NN(self.input_dim,self.output_dim,**self.parameters).to(device)
        #else:
        #    model=NN(self.input_dim, self.output_dim).to(device)
        # dataLoader
        inputs=torch.tensor(X_train, dtype=torch.float32).to(device)
        targets=torch.tensor(Y_train, dtype=torch.float32).to(device)
        dataset=TensorDataset(inputs,targets)
        dataloader=DataLoader(dataset,batch_size=batch_size,shuffle=True)
        #Loss and Optimizer
        optimizer=torch.optim.SGD(model.parameters(),lr=learning_rate,
                                weight_decay=l2_lambda,
                                momentum=0.9
                                )
        scheduler = ReduceLROnPlateau(optimizer, 
                        mode='min',       # Monitor validation loss
                        factor=0.5,       # Reduce LR by 2x
                        patience=5
                                    )
        losses=[]
        for epoch in range(epochs):
            model.train()
            epoch_loss=0
            for X_batch,Y_batch in dataloader:
                optimizer.zero_grad()
                # Forward
                pred=model(X_batch)
                loss=loss_function(pred,Y_batch)
                l1_norm=sum(p.abs().sum() for p in model.parameters())
                loss+=l1_lambda*l1_norm
                # Backward and optimize
                loss.backward()
                optimizer.step()
                epoch_loss += loss.item() * batch_size
            scheduler.step(epoch_loss)
            current_lr = optimizer.param_groups[0]['lr']
            avg_loss = epoch_loss / len(dataset)
            losses.append(avg_loss)
            if to_print==True and epoch%10==0:
                print ('Epoch [{}/{}], Loss: {:.4f}, current learning rate:{}'.format(epoch+1, epochs, avg_loss,current_lr))
            if current_lr<10**(-5):
                break
        self.model=model
        return np.array(losses+[losses[-1]]*(epochs-len(losses)))


    def predict(self,X_test):
        """
        Génerer les predictions et Calculer des metrics en fonction du modèle:

        Args:
            model: instance de la classe MLP entrainé
            X_test: variables explicatives de test 
        """
        if self.preprocessing is not None:
            X_test=self.preprocessing.transform(X_test)        
        self.model.eval()
        with torch.no_grad():
            test_inputs=torch.tensor(X_test, dtype=torch.float32).to(device)
            pred=self.model(test_inputs)
        return pred

            