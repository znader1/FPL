#%%
import constraint

problem = constraint.Problem()

# The maximum amount of each coin type can't be more than 60
# (coin_value*num_of_coints) <= 60

problem.addVariable("1 cent", range(61))
problem.addVariable("3 cent", range(21))
problem.addVariable("5 cent", range(13))
problem.addVariable("10 cent", range(7))
problem.addVariable("20 cent", range(4))

#%%

problem.addConstraint(
    constraint.ExactSumConstraint(60,[1,3,5,10,20]),
    ["1 cent", "3 cent", "5 cent","10 cent", "20 cent"]
)
# Where we explicitly give the order in which the weights should be allocated

# We could've used a custom constraint instead, BUT in this case the program will
# run slightly slower - this is because built-in functions are optimized and
# they find the solution more quickly
# def custom_constraint(a, b, c, d, e):
#     if a + 3*b + 5*c + 10*d + 20*e == 60:
#         return True
#     problem.addConstraint(o, ["1 cent", "3 cent", "5 cent","10 cent", "20 cent"])


# A function that prints out the amount of each coin
# in every acceptable combination
#%%

def print_solutions(solutions):
    for s in sols:
        print("---")
        print("""
        1 cent: {0:d}
        3 cent: {1:d}
        5 cent: {2:d}
        10 cent: {3:d}
        20 cent: {4:d}""".format(s["1 cent"], s["3 cent"], s["5 cent"], s["10 cent"], s["20 cent"]))
        # If we wanted to we could check whether the sum was really 60
        # print("Total:", s["1 cent"] + s["3 cent"]*3 + s["5 cent"]*5 + s["10 cent"]*10 + s["20 cent"]*20)
        # print("---")

solutions = problem.getSolutions()
#print_solutions(solutions)
print("Total number of ways: {}".format(len(solutions)))

# %%

### FANTASY
problem = constraint.Problem()

# The maximum amount of each coin type can't be more than 60
# (coin_value*num_of_coints) <= 60

problem.addVariable("G", [5.1,5.3])
problem.addVariable("D", range(4))
problem.addVariable("M", range(4))
problem.addVariable("F", range(2))

# %%
# def sum_constraint(GK1, GK2, DEF1, DEF2, DEF3, DEF4,DEF5,MID1,MID2,MID3,MID4,MID5,FOR1,FOR2,FOR3):
#     if (GK1 + GK2 +DEF1 + DEF2 + DEF3 +DEF4 +DEF5+MID1+MID2+MID3+MID4+MID5+FOR1+FOR2+FOR3 <=100.0):
#         return True

def sum_constraint(G,D,M,F):
    if (G+D+M+F <=100.0):
        return True
#%%
# problem.addConstraint(
#     constraint.ExactSumConstraint(100,[2,5,5,3]),
#     ["GK", "DEF", "MID","FOR"]
# )

problem.addConstraint(sum_constraint, "GDMF")

# %%
solutions = problem.getSolutions()
print("Number of solutions found: {}\n".format(len(solutions)))

# %%
for s in solutions:
    print("G = {}, D = {}, M = {}, F = {}"
        .format(s['G'], s['D'], s['M'], s['F']))

# %%
#### Each player

### FANTASY
problem = constraint.Problem()

# The maximum amount of each coin type can't be more than 60
# (coin_value*num_of_coints) <= 60

# %%

# %%
problem = constraint.Problem()
problem.addVariables("AB", list(set(FPL_data[FPL_data['element_type'] == 1]['now_cost'])))
problem.addVariables("CDEFG", list(set(FPL_data[FPL_data['element_type'] == 2]['now_cost'])))
problem.addVariables("HIJKL", list(set(FPL_data[FPL_data['element_type'] == 3]['now_cost'])))
problem.addVariables("MNO", list(set(FPL_data[FPL_data['element_type'] == 4]['now_cost'])))

#%%

def sum_constraint(A,B,C,D,E,F,G,H,I,J,K,L,M,N,O):
    if ((A+B+C+D+E+F+G+H+I+J+K+L+M+N+O <=1000.0) & (A+B+C+D+E+F+G+H+I+J+K+L+M+N+O >=900 )):
        return True
#%%
# problem.addConstraint(
#     constraint.ExactSumConstraint(100,[2,5,5,3]),
#     ["GK", "DEF", "MID","FOR"]
# )

problem.addConstraint(sum_constraint, "ABCDEFGHIJKLMNO")
problem.addConstraint(constraint.AllDifferentConstraint())

# %%
solutions = problem.getSolutions()
print("Number of solutions found: {}\n".format(len(solutions)))


# %%
