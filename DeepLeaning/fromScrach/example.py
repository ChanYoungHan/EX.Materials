import numpy as np
from dezero import Variable
from dezero.utils import plot_dot_graph

x0 = Variable(np.array(1.0), name="x0")
x1 = Variable(np.array(1.0), name="x1")
y = (x0 + x1) ** 2
y.name = "y"
print(y)
print(plot_dot_graph(y))
