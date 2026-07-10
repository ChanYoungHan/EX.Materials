import numpy as np
import unittest
import time
import weakref
import contextlib

class SquareTest(unittest.TestCase):
    def test_forward(self):
        x = Variable(2.0)
        y = square(x)
        expected = np.array(4.0)
        self.assertEqual(y.data, expected)
    
    def test_backward(self):
        x = Variable(3.0)
        y = square(x)
        y.backward()
        expected = np.array(6.0)
        self.assertEqual(x.grad, expected)
    
    def test_gradient_check(self):
        x = Variable(np.random.rand(1))
        y = square(x)
        y.backward()
        num_grad = numerical_diff(square, x)
        flg = np.allclose(x.grad, num_grad)
        self.assertTrue(flg)









class Square(Function):
    def forward(self, x):
        y = x ** 2
        return y
    
    def backward(self, gy):
        x = self.inputs[0].data
        gx = 2 * x * gy
        return gx

class Exp(Function):
    def forward(self, x):
        return np.exp(x)
    
    def backward(self, gy):
        x = self.inputs[0].data
        gx = gy * np.exp(x)
        return gx




def numerical_diff(f, x, esp=1e-4):
    x0 = Variable(x.data - esp)
    x1 = Variable(x.data + esp)
    y0 = f(x0)
    y1 = f(x1)
    return (y1.data - y0.data) / (2 * esp)






def square(x):
    return Square()(x)

def exp(x):
    return Exp()(x)


a = Variable(np.array(3.0))
b = Variable(np.array(2.0))
c = Variable(np.array(1.0))

# y = add(mul(a,b),c)
y = a * b + c
y.backward()

print(y)
print(a.grad)
print(b.grad)

a.cleargrad()
b.cleargrad()
y2 = np.array(2.0) + y
y2.backward()
print(a.grad)
print(b.grad)

y3 = 2 * y2
print(y2, y3)
