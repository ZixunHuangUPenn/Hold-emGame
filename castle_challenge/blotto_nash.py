"""Two-player castle game (Game 1) minimax: fictitious play.
Payoff depends only on the opponent's per-castle marginal distributions,
so the best response to any mixture is an exact DP."""
import numpy as np
V=np.array([1,2,3,4,5]); N=100; K=5
def val_table(M):                       # M[i,s] = P(opp sends s to castle i)
    less=np.cumsum(M,1)-M
    return V[:,None]*(less+0.5*M)
def br(M):
    val=val_table(M); dp=np.full((K+1,N+1),-1e9); dp[0,0]=0; arg=np.zeros((K+1,N+1),int)
    for i in range(K):
        for t in range(N+1):
            c=dp[i,:t+1][::-1]+val[i,:t+1]; s=c.argmax(); dp[i+1,t]=c[s]; arg[i+1,t]=s
    a=[];t=N
    for i in range(K,0,-1): a.append(arg[i,t]); t-=a[-1]
    return np.array(a[::-1]),dp[K,N]
def onehot(a):
    M=np.zeros((K,N+1)); M[np.arange(K),a]=1; return M
M=onehot(np.array([7,13,20,27,33])).astype(float); T=1
for t in range(1,20001):
    a,_=br(M/T); M+=onehot(a); T+=1
    if t in (100,1000,5000,20000):
        print(f"iter {t:6d}: opponent's best reply vs our mixture gets {br(M/T)[1]:.3f} (game value 7.5)")
P=M/T
print("\nper-castle mean soldiers:", np.round((P*np.arange(N+1)).sum(1),1),
      " proportional = ", np.round(100*V/15,1))
for i in range(K):
    nz=np.nonzero(P[i]>1e-3)[0]
    print(f"castle {V[i]}: support {nz.min()}..{nz.max()}  "
          f"(theory uniform on 0..{200*V[i]/15:.0f})  P(0)={P[i,0]:.2f}")
print("\nexploitability of pure strategies (what a best reply scores vs you):")
for a in [[20]*5,[7,13,20,27,33],[0,0,33,33,34],[2,2,25,35,36],[0,10,20,30,40]]:
    print(f"  {a}: {br(onehot(np.array(a)))[1]:.2f}")
np.save("nash_marginals.npy",P)
