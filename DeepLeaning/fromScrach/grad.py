import numpy as np
import math
from dezero import Function, Variable
from dezero.utils import plot_dot_graph


def set_up():
    import os, sys

    fd = os.path.abspath(__file__)
    if fd in sys.path:
        print("already installed")
    else:
        print("install success")


class Sin(Function):
    def forward(self, x):
        y = np.sin(x)
        return y

    def backward(self, gy):
        x = self.inputs[0].data
        gx = gy * np.cos(x)
        return gx


def sin(x):
    return Sin()(x)


def my_sin(x, threshold=0.0001):
    y = 0
    for i in range(100000):
        c = (-1) ** i / math.factorial(2 * i + 1)
        t = c * x ** (2 * i + 1)
        y += t
        if abs(t.data) < threshold:
            break
    return y


def rosenbrock(x0, x1):
    y = 100 * (x1 - x0 ** 2) ** 2 + (1 - x0) ** 2
    return y


set_up()
script_type = "new"
if script_type == "torch":

    import torch
    import numpy as np

    x_numpy = np.array(2.0)
    x_tensor = torch.tensor(x_numpy, requires_grad=True)

    print(x_numpy, x_tensor)

    y = x_tensor ** 2
    y.backward(create_graph=True)
    gx = x_tensor.grad
    print(y, gx)

    z = gx ** 3 + y
    z.backward()
    print(x_tensor.grad)

elif script_type == "gradient of sin":
    x = Variable(np.array(np.pi / 4))
    y1 = sin(x)
    y1.backward()

    print(y1.data)
    print(x.grad)

    x.cleargrad()
    y2 = my_sin(x)
    y2.backward()
    plot_dot_graph(y2)

    print(y2.data)
    print(x.grad)

elif script_type == "rosenbrock":
    x0 = Variable(0.0)
    x1 = Variable(2.0)

    lr = 0.001
    iters = 1000

    for i in range(iters):
        print(x0, x1)

        y = rosenbrock(x0, x1)
        x0.cleargrad()
        x1.cleargrad()
        y.backward()

        x0 -= lr * x0.grad
        x1 -= lr * x1.grad

elif script_type == "second gradient":

    def f(x):
        y = x ** 4 - 2 * x ** 2
        return y

    x = Variable(2.0)
    y = f(x)
    print("backward start")
    y.backward(create_graph=True)
    print(x.grad)

    gx = x.grad
    x.cleargrad()
    gx.backward()
    print(x.grad)

elif script_type == "multi gradient of sin":
    import dezero.functions as F
    import matplotlib.pyplot as plt

    x = Variable(np.linspace(-7, 7, 200))
    y = F.sin(x)
    y.backward(create_graph=True)

    logs = [y.data]

    for i in range(3):
        logs.append(x.grad.data)
        gx = x.grad
        x.cleargrad()
        gx.backward(create_graph=True)

    labels = ["y=sin(x)", "y'", "y''", "y'''"]
    for i, v in enumerate(logs):
        plt.plot(x.data, logs[i], label=labels[i])
    plt.legend(loc="lower right")
    plt.show()

elif script_type == "tanh":
    import dezero.functions as F

    x = Variable(1)
    y = F.tanh(x)
    x.name = "x"
    y.name = "y"
    y.backward(create_graph=True)

    iters = 0

    for i in range(iters):
        gx = x.grad
        x.cleargrad()
        gx.backward(create_graph=True)

    gx = x.grad
    gx.name = "gx" + str(iters + 1)
    plot_dot_graph(gx, verbose=False, to_file="tanh.png")

elif script_type == "reshape-transpose":
    import dezero.functions as F

    input_numpy_array = np.array([[1, 2, 3], [4, 5, 6]])
    to_reshape_arg = (3, 2)
    x = Variable(input_numpy_array)
    y = F.reshape(x, to_reshape_arg)
    z = F.transpose(y)
    z.backward(retain_grad=True)
    print(x)
    print(y)
    print(z)
    print(x.grad)

elif script_type == "new":
    import dezero.functions as F

    input_numpy_array = np.array([[1, 2, 3], [4, 5, 6]])

    x = Variable(input_numpy_array)
    y = F.sum(x, axis=0)
    y.backward()
    print(x)
    print(y)
    print(x.grad)
    x.cleargrad()

    y = Variable(10)
    z = x + y
    z.backward()

    print(x.grad)
    print(y.grad)
