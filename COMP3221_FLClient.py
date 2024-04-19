import sys
import socket
import threading
import json
import pickle
import pandas as pd
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
import matplotlib.pyplot as plt
import time

HOST = "localhost"
SERVER_PORT = 6000

class Client:
    def __init__(self, id, port, opt_method):
        self.client_id = id
        self.port = port
        self.opt_method = opt_method
        self.stop_event = threading.Event()
        self.X_train = None
        self.X_test = None
        self.Y_train = None
        self.Y_test = None
        self.model = None
        self.opt = None
        self.loss_fn = F.mse_loss
        self.epochs = 100
        self.learning_rate = 1e-7
        self.confirmed = False
        self.iteration = 0
        
    def start(self):
        print(f"I am client {self.client_id.strip("client")}")
        self.create_log()
        self.retrieve_data()
        self.listener_thread = threading.Thread(target=self.listen_to_server)
        self.listener_thread.start()
        self.send_message(f"CONNECTION ESTABLISHED")

    def stop(self):
        try:
            self.stop_event.set()
            self.listener_thread.join()
        except Exception:
            pass

    def listen_to_server(self):  # Listen on port 6001, 6002, etc.
        print(f"Client listening on port {self.port}")
        while True:
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client_socket:
                    client_socket.bind((HOST, self.port))
                    client_socket.listen(5)
                    
                    conn, addr = client_socket.accept()
                    with conn:
                        try:
                            data = conn.recv(1)
                            if data == b"0":
                                data = b""
                                while True:
                                    packet = conn.recv(1048)
                                    if not packet:
                                        break
                                    data += packet
                                if data:
                                    try:
                                        model = pickle.loads(data)
                                        self.model = model["model"]
                                        self.opt = optim.SGD(self.model.parameters(), lr=self.learning_rate)
                                        self.iteration = model["iteration"]
                                        self.confirmed = False
                                        print(f"\nReceived global model {self.iteration + 1} from server")
                                        self.write_log(f"\nReceived global model {self.iteration + 1} from server")
                                        update = threading.Thread(target=self.update)
                                        update.start()
                                    except Exception as e:
                                        print(f"Failed: {e}")
                                
                            elif data == b"1":
                                self.confirmed = True
                        except Exception as e:
                            print("Could not read from server: {e}")
                    client_socket.close()
            except Exception as e:
                print(f"Can't connect to the listener socket: {e}")

    def send_message(self, message):
        message = {
            "client_id": self.client_id,
            "port": self.port,
            "data_size": list(self.X_train.size())[0],
            "content": message,
        }

        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client_socket:
                client_socket.connect((HOST, SERVER_PORT))
                client_socket.sendall(b"0")
                client_socket.sendall(json.dumps(message).encode())
                print(f"Message sent to server: {message["content"]}")
                client_socket.close()
        except Exception as e:
            print(f"Message failed: {e}")
            
    def send_model(self):
        sent = False
        message = {
            "client_id": self.client_id,
            "iteration": self.iteration,
            "model": self.model,
        }
        while not sent:
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client_socket:
                    client_socket.connect((HOST, SERVER_PORT))
                    client_socket.sendall(b"1")
                    client_socket.sendall(pickle.dumps(message))
                    time.sleep(0.1)
                    sent = self.confirmed
                    self.confirmed = False
                    client_socket.close()
            except Exception as e:
                print(f"Model failed to send: {e}")
        print("\tModel sent to server")
    
    def evaluate(self):
        pred = self.model(self.X_test)
        loss = self.loss_fn(pred, self.Y_test)
        print(f"\tTesting MSE: {loss:.04f}")
        self.write_log(f"\tTesting MSE: {loss:.04f}")
        return loss
    
    def update(self):
        self.evaluate()
        print(f"\tUpdating local model:")
        if self.opt_method == 0:
            self.gradient_descent()
        else:
            self.mini_batch()
        self.send_model()
    
    def gradient_descent(self):
        """Performs the gradient descent algorithm on the current model.
        This multiple times, as determined by self.epochs.
        The MSE result before and after all epochs are printed to the terminal and
        saved in the logs.
        """
        losses = []
        for e in range(self.epochs):
            pred = self.model(self.X_train)
            loss = self.loss_fn(pred, self.Y_train)
            losses.append(loss)
            loss.backward()
            self.opt.step()
            self.opt.zero_grad()
        print(f"\tPre-update training MSE: {losses[0]:.04f}")
        print(f"\tPost-update training MSE: {losses[-1]:.04f}")
        self.write_log(f"\tPre-update training MSE: {losses[0]:.04f}")
        self.write_log(f"\tPost-update training MSE: {losses[-1]:.04f}")
    
    def mini_batch(self):
        pass

    def retrieve_data(self):
        """Retrieves the training data and testing data for the client from the files.
        This data is stored inside the client instance and used for evaluating and training
        the model in each iteration.
        """
        # retrieve training data
        df = pd.read_csv(f"./FLData/calhousing_train_{self.client_id}.csv")
        X_train = df.iloc[:, :-1].values
        y_train = df.iloc[:, -1].values
        self.X_train = torch.Tensor(X_train).type(torch.float32)
        self.Y_train = torch.Tensor(y_train).type(torch.float32).unsqueeze(1)
        
        # retrieve testing data
        df = pd.read_csv(f"./FLData/calhousing_test_{self.client_id}.csv")
        X_test = df.iloc[:, :-1].values
        y_test = df.iloc[:, -1].values
        self.X_test = torch.Tensor(X_test).type(torch.float32)
        self.Y_test = torch.Tensor(y_test).type(torch.float32).unsqueeze(1)
        print("Data retrieved from files")
        
    def create_log(self) -> None:
        try:
            with open(f"./FLLogs/{self.client_id}_log.txt", "w") as f:
                f.close()
        except IOError as e:
            print(f"Error creating log file: {e}")
        
    def write_log(self, message: str) -> None:
        try:
            with open(f"./FLLogs/{self.client_id}_log.txt", "a") as f:
                f.write(message + "\n")
                f.close()
        except IOError as e:
            print(f"Error with writing to log: {e}")
    
if __name__ == "__main__":
    id = sys.argv[1]
    port = int(sys.argv[2])
    opt_method = int(sys.argv[3])
    client = Client(id, port, opt_method)
    client.start()