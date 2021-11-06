import numpy as np
from dezero.core import Function


class Sin(Function):
    def forward(self, x):
        y = np.sin(x)
        return y

    def backward(self, gy):
        x = self.inputs
        gx = gy * np.cos(x)
        return gx


class Cos(Function):
    def forward(self, x):
        y = np.cos(x)
        return y

    def backward(self, gy):
        x = self.inputs
        gx = gy * -np.sin(x)
        return gx


def sin(x):
    return Sin()(x)


def cos(x):
    return Cos()(x)
