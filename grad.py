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
