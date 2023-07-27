import numpy as np
import matplotlib.pyplot as plt
from scipy.integrate import nquad

from welib.tools.tictoc import Timer
from welib.tools.spectral import fft_wrap
from welib.stoch.utils import autocovariance_int
from welib.stoch.utils import autocovariance_fft
from welib.stoch.utils import autospectrum_int
from welib.stoch.utils import autospectrum_fft
from welib.stoch.utils import autocorrcoeff_num
from welib.stoch.utils import sample_from_autospectrum

class SampledStochasticProcess:
    def __init__(self, generator=None, name='', omega_max=10, tau_max=10, time_max=10, nDiscr=100,
            verbose=False):
        self.name = name
        self.verbose = verbose


        # Default domains
        self.omega_max  = omega_max
        self.tau_max    = tau_max
        self.time_max   = max(time_max,tau_max)
        self.nDiscr     = nDiscr

        # Sample generations using a generator
        self.generator = generator
        self.time = None

        # Samples
        self.xi   = None  # nSamples x nTime

        # if analytical values exists
        self._f_kappa_XX_th = None  # interface: kappa_XX(tau)
        self._f_S_X_th      = None  # interface: S_X(om)
        self._var_th       = None
        self._mu_th        = None
        self._S_X_th_i     = {}
        self._kappa_XX_th_i = {}

        # Sample stats
        self._tau     = None
        self._omega   = None
        self.mu_xi    = None
        self.var_xi   = None
        self.kappa_XX = None
        self.rho_XX   = None
        self.S_X      = None
        self.S_avg    = None

    @property
    def nSamples(self):
        if self.xi is None:
            return 0
        return self.xi.shape[0]

    @property
    def time_detault(self):
        if self.time is not None:
            return self.time
        return np.linspace(0, self.time_max, self.nDiscr)

    @property
    def tau_detault(self):
        return np.linspace(0, self.tau_max, self.nDiscr)

    @property
    def omega_default(self):
        return np.linspace(0, self.omega_max, self.nDiscr)

    @property
    def tau(self):
        if self._tau is not None:
            return self._tau
        else:
            return self.tau_detault

    @property
    def omega(self):
        if self._omega is not None:
            return self._omega
        else:
            return self.omega_default

    def generate_samples(self, nSamples=1, time=None):
        """ 
        Generate time series samples for stochastic process X(t)
            x = generator(time): [array]
        """
        if time is None:
            time = self.time_detault
        self.time = time
        xi=np.zeros((nSamples, len(time)))
        for i in range(nSamples):
            xi[i,:] = self.generator(time)
        self.xi = xi
        return xi

    def generate_samples_from_autospectrum(self, nSamples=1, time=None, method='ifft', **kwargs):
        if time is None:
            time = self.time_detault
        self.time = time

        tMax = time[-1]
        dt = (time[-1]-time[0])/(len(time)-1)

        xi=np.zeros((nSamples, len(time)))
        if not self._f_S_X_th:
            raise Exception('Provide an autospectrum function')
        f_S = self._f_S_X_th
        with Timer('Gen. samples from spectrum - {} ...'.format(method), writeBefore=True, silent=not self.verbose):
            for i in range(nSamples):

                #def sample_from_autospectrum(tMax, dt, f_S, angularFrequency=True, 
                #        method='ifft', fCutInput=None):
                _, xi[i,:], _, _ = sample_from_autospectrum(tMax, dt, f_S, angularFrequency=True, method=method, **kwargs) 
        self.xi = xi
        return xi



    def samples_stats(self, nTau=None, stats=None):
        """ 
        """
        if stats is None:
            stats=['correlation','avg_spectra']
        time = self.time
        xi   = self.xi

        dt=(time[-1]-time[0])/(len(time)-1)

        # --- Basic stats
        self.mu_xi  = np.mean(xi, axis = 0)
        self.var_xi = np.var(xi, axis  = 0)


        # --- Average spectra
        if 'avg_spectra' in stats:
            f0, S_X0, Info = fft_wrap(time, xi[0,:], output_type='psd', averaging='None', detrend=False)
            S_i = np.zeros((self.nSamples, len(f0)))
            with Timer('Samples spectra', writeBefore=True, silent=not self.verbose):
                for i in range(self.nSamples):
                    f, S_i[i,:], Info = fft_wrap(time, xi[i,:], output_type='psd', averaging='None', detrend=False)
                S_avg = np.mean(S_i, axis=0)/(2*np.pi)
            self.om_Savg    =  2*np.pi*f
            self.S_avg      =  S_avg
        
        # --- Correlation
        if 'correlation' in stats:
            with Timer('Samples correlations', writeBefore=True, silent=not self.verbose):
                if nTau is None:
                    nTau = int(self.tau_max/dt)
                    #nTau = len(time)
                kappa_XXi = np.zeros((self.nSamples, nTau))
                rho_XXi   = np.zeros((self.nSamples, nTau))
                for i in range(self.nSamples):
                    if np.mod(i,10)==0 and self.verbose:
                        print('Correlation', i, self.nSamples)
                    rho_XXi[i,:], tau = autocorrcoeff_num(xi[i,:], nMax=nTau, dt=dt, method='numpy')
                    kappa_XXi[i,:] = rho_XXi[i,:] * np.var(xi[i,:])
                    #, tau = autocovariance_num(xi[i,:], nMax=nTau, dt=dt, method='manual')

            kappa_XX = np.mean(kappa_XXi, axis=0)
            rho_XX = np.mean(rho_XXi, axis=0)
            self._tau     =  tau      
            self.kappa_XX =  kappa_XX 
            self.rho_XX   =  rho_XX   

            # --- Autospectrum from kappa num..Not the best
            # TODO this might not be right (factor 2 maybe?)
            #om, S_X = autospectrum_fft(tau, kappa_XX, onesided=True, method='fft_wrap')
            om, S_X = autospectrum_fft(tau, kappa_XX, onesided=True, method='rfft')
            self._omega   =  om       
            self.S_X      =  S_X      



    # --------------------------------------------------------------------------------}
    # --- Functions using analytical/lambda functions provided
    # --------------------------------------------------------------------------------{
    def autospectrum_int(self, omega=None, tau_max=None, method='quad', nDiscr=None):
        if omega is None:
            omega = self.omega_default
        if tau_max is None:
            #tau_max = np.max(self.time_detault)
            tau_max = self.tau_max

        if not self._f_kappa_XX_th:
            raise Exception('Provide an autocovariance function')

        if self.verbose:
            print('>> S_X(omega) from int k_XX(tau), method:{}, with tau=[{} ; {} ]'.format(method, 0, tau_max))
        if method=='quad':
            if self.verbose:
                print('                         omega from {} to {} delta:{}'.format(omega[0], omega[-1], omega[1]-omega[0]))
            S_X_i = autospectrum_int(omega, self._f_kappa_XX_th, tau_max=tau_max)

        elif method=='fft':
            if nDiscr is None:
                nDiscr=self.nDiscr
            tau = np.linspace(0, tau_max, nDiscr)
            kappa_XX = np.array([self._f_kappa_XX_th(t) for t in tau])
            omega, S_X_i = autospectrum_fft(tau, kappa_XX, onesided=True, method='rfft')
            #omega, S_X_i = autospectrum_fft(tau, kappa_XX, onesided=True, method='fft_wrap')
#             dtau = tau[1]-tau[0]
#             print('tau_max', tau[-1])
#             print('dtau',  tau[1]-tau[0])
#             print('1/dtau',  1/dtau)
#             print('n   ',  len(tau))
#             S_X_i*=tau_max/2
#             S_X_i*=5
        else:
            raise NotImplementedError()

        self._S_X_th_i[method] = (omega, S_X_i)



        return S_X_i

    def autocovariance_int(self, tau=None, omega_max=None, method='quad', nDiscr=None):
        if tau is None:
            tau = self.tau_detault
        if omega_max is None:
            omega_max = self.omega_max

        if not self._f_S_X_th:
            raise Exception('Provide an autospectrum function')

        if self.verbose:
            print('>> k_XX(tau) from int S_X(omega), method:{}, with omega=[{} ; {} ]'.format(method,0, omega_max))
        if method=='quad':
            if self.verbose:
                print('                         tau from {} to {} delta:{}'.format(tau[0], tau[-1], tau[1]-tau[0]))
            kappa_XX = autocovariance_int(tau, self._f_S_X_th, omega_max=omega_max)
        elif method=='fft':
            if nDiscr is None:
                nDiscr=self.nDiscr

            omega = np.linspace(0, omega_max, nDiscr)
            # If we want to respect tau_max...
            #domega = np.pi/self.tau_max
            #omega = np.arange(0, omega_max, domega)

            S_X = np.array([self._f_S_X_th(abs(om)) for om in omega])
            #omega = np.linspace(-omega_max, omega_max, self.nDiscr)
            #S_XX = np.array([self._f_S_X_th(abs(om)) for om in omega])/2
            tau, kappa_XX = autocovariance_fft(omega, S_X, onesidedIn=True)
        else:
            raise NotImplementedError()

        self._kappa_XX_th_i[method] = (tau, kappa_XX)

        return kappa_XX

    def autospectrum_moments(self, orders=None, method='num'):
        if orders is None:
            orders=[0,1,2,3]
        if not self._f_S_X_th:
            raise Exception('Provide an autospectrum function')
        if method=='num':
            omega = self.omega_default
            S_X = np.array([self._f_S_X_th(abs(om)) for om in omega])

        moments=dict()
        for i in orders:
            if method=='quad':
                integrand = lambda omega : omega**i * self._f_S_X_th(omega)
                moments[i], _ = nquad(integrand, [[0, self.omega_max]] )
            else:
                moments[i] = np.trapz( S_X * omega**i , omega)

        return moments

    # --------------------------------------------------------------------------------}
    # --- Plots 
    # --------------------------------------------------------------------------------{
    def plot_samples(self, ax=None, maxSamples=5):
        # --- Plot realisations
        if ax is None:
            fig,ax = plt.subplots(1, 1, sharey=False, figsize=(6.4,4.8)) # (6.4,4.8)
            fig.subplots_adjust(left=0.12, right=0.95, top=0.95, bottom=0.11, hspace=0.20, wspace=0.20)
        for i in range(min(self.nSamples,maxSamples)):
            ax.plot(self.time, self.xi[i], label='')
        ax.set_xlabel('Time [s]')
        ax.set_ylabel('')
        #ax.legend()
        ax.set_title(self.name)
        return ax


    def plot_mean(self, ax=None):
        # --- Plot mean and sigma
        if ax is None:
            fig,ax = plt.subplots(1, 1, sharey=False, figsize=(6.4,4.8)) # (6.4,4.8)
            fig.subplots_adjust(left=0.12, right=0.95, top=0.95, bottom=0.11, hspace=0.20, wspace=0.20)
        if self.mu_xi: 
            ax.plot(self.time, self.mu_xi , label='Mean')
        if self._mu_th is not None:
            ax.plot(self.time, self.time*0+self._mu_th, 'k--' , label='Mean (th)')
        #ax.plot(time, var_xi , label='Variance')
        #ax.plot(time, time*0+s**2, 'k--' , label='Variance (th)')
        ax.set_xlabel('Time [s]')
        ax.set_ylabel('mu_X(t)')
        #ax.legend()
        ax.set_title(self.name)
        return ax

    def plot_var(self, ax=None):
        # --- Plot mean and sigma
        if ax is None:
            fig,ax = plt.subplots(1, 1, sharey=False, figsize=(6.4,4.8)) # (6.4,4.8)
            fig.subplots_adjust(left=0.12, right=0.95, top=0.95, bottom=0.11, hspace=0.20, wspace=0.20)
        if self.var_xi is not None: 
            ax.plot(self.time, self.var_xi , label='Variance')
            ax.plot(self.time, self.time*0+np.mean(self.var_xi ), '--' ,c=(0.5,0.5,0.5))
            if self.verbose:
                print('>>> Mean Var num:', np.around(np.mean(self.var_xi ),4))
        if self._var_th is not None:
            ax.plot(self.time, self.time*0+self._var_th, 'k--' , label='Variance (th)')
            if self.verbose:
                print('>>> Mean Var th :', np.around(self._var_th,4))
        #ax.plot(time, var_xi , label='Variance')
        ax.set_xlabel('Time [s]')
        ax.set_ylabel('VarX(t)')
        #ax.legend()
        ax.set_title(self.name)
        return ax

    def plot_autocovariance(self, ax=None):
        # --- Plot AutoCovariance
        if ax is None:
            fig,ax = plt.subplots(1, 1, sharey=False, figsize=(6.4,4.8)) # (6.4,4.8)
            fig.subplots_adjust(left=0.12, right=0.95, top=0.95, bottom=0.11, hspace=0.20, wspace=0.20)
        if self.kappa_XX is not None: 
            ax.plot(self.tau, self.kappa_XX, label='kappa_mean')
            if self.verbose:
                print('>>> Correlation length num', np.around(np.trapz(self.kappa_XX, self.tau,4)))

        if self._f_kappa_XX_th is not None:
            #kappa_XX_th = self._f_kappa_XX_th(self.tau)
            k_XX = [self._f_kappa_XX_th(t) for t in self.tau]
            ax.plot(self.tau, k_XX , 'k--', label='kappa theory')
            if self.verbose:
                print('>>> Correlation length th ', np.around(np.trapz(k_XX, self.tau,4)))

        for k,v in self._kappa_XX_th_i.items():
            tau, k_XX = self._kappa_XX_th_i[k]
            ax.plot(tau, k_XX,':'   , label=r'$\int S_X$ provided')
            ax.set_xlim([0,self.tau_max])
            if self.verbose:
                print('>>> Correlation length {:s}'.format(k[:3]), np.around(np.trapz(k_XX, tau,4)))
        ax.set_xlabel('Tau [s]')
        ax.set_ylabel('kappa_XX')
        ax.legend()
        ax.set_title(self.name)
        return ax

    def plot_autocorrcoeff(self, ax=None):
        # --- Plot AutoCorrCoeff
        if ax is None:
            fig,ax = plt.subplots(1, 1, sharey=False, figsize=(6.4,4.8)) # (6.4,4.8)
            fig.subplots_adjust(left=0.12, right=0.95, top=0.95, bottom=0.11, hspace=0.20, wspace=0.20)
        # for i in range(min(nSamples,5)):
        #     ax.plot(tau, rho_XXi[i,:], alpha=0.5)
        if self.rho_XX is not None:
            ax.plot(self.tau, self.rho_XX, label='rho_mean (num)')

        if self._f_kappa_XX_th and self._var_th :
            #kappa_XX_th = self._f_kappa_XX_th(self.tau)
            k_XX = np.array([self._f_kappa_XX_th(t) for t in self.tau])
            rho_XX_th = k_XX / self._var_th
            ax.plot(self.tau, rho_XX_th , 'k--', label=r'$\rho_XX$ provided')

        for k,v in self._kappa_XX_th_i.items():
            tau, k_XX = self._kappa_XX_th_i[k]
            ax.plot(tau, k_XX / self._var_th ,':'   , label=r'$\int S_X$ provided')
            ax.set_xlim([0,self.tau_max])

        ax.set_xlabel('Tau [s]')
        ax.set_ylabel('rho_XX')
        ax.legend()
        ax.set_title(self.name)
        return ax

    
    def plot_autospectrum(self, ax=None):
        # --- auto
        if ax is None:
            fig,ax = plt.subplots(1, 1, sharey=False, figsize=(6.4,4.8)) # (6.4,4.8)
            fig.subplots_adjust(left=0.12, right=0.95, top=0.95, bottom=0.11, hspace=0.20, wspace=0.20)
        # ax.plot([omega_0,omega_0], [0,S_X_th] ,'k--'   , label='Theory', lw=2)
        if self.S_X is not None:
            ax.plot(self.omega, self.S_X ,'o-', label='FFT (kappa_num)')
            if self.verbose:
                print('>>> Spectrum integration num', np.around(np.trapz(self.S_X, self.omega),4))

        if self.S_avg is not None:
            ax.plot(self.om_Savg, self.S_avg ,'.-', label='FFT (avg)')
            if self.verbose:
                print('>>> Spectrum integration avg', np.around(np.trapz(self.S_avg, self.om_Savg),4))

        if self._f_S_X_th is not None:
            #S_X_th = self._f_S_X_th(self.omega)
            S_X_th = [self._f_S_X_th(om) for om in self.omega]
            ax.plot(self.omega, S_X_th ,'k--', label='S_X(omega) provided')
            if self.verbose:
                print('>>> Spectrum integration th ', np.around(np.trapz(S_X_th, self.omega),4))

        for k,v in self._S_X_th_i.items():
            om, S_X = self._S_X_th_i[k]
            ax.plot(om, S_X ,':'   , label=r'$\int \kappa$ provided {}'.format(k))
            b = om<self.omega_max # WEIRD
            #b = om>0
            ax.set_xlim([0,self.omega_max])
            if self.verbose:
                print('>>> Spectrum integration {:s}'.format(k[:3]), np.around(np.trapz(S_X[b], om[b]),4))
        ax.set_xlabel(r'$\omega$ [rad/s]')
        ax.set_ylabel(r'$S_X(\omega)$')
        ax.legend()
        ax.set_title(self.name)
        return ax

