import numpy as np
import math
from dezero import Function, Variable
from dezero.utils import plot_dot_graph


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


def rosenbrock2_1(x0, x1):
    y = 200 * (x1 - x0 ** 2)
    return y


def rosenbrock2_0(x0, x1):
    y = -400 * x0 * (x1 - x0 ** 2) - 2 * (1 - x0)
    return y


script_type = "rosenbrock"
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

elif script_type == "tailer":
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
        # print(x0.grad, x1.grad)

        y = rosenbrock(x0, x1)
        x0.cleargrad()
        x1.cleargrad()
        y.backward()
        print(x0.grad, x1.grad)

        x0 -= lr * x0.grad
        x1 -= lr * x1.grad
