# -*- coding: utf-8 -*-
"""
This module provides functions related to the flockwork
temporal network model.
"""

import numpy as np
from numpy import random

from scipy.integrate import ode
from scipy.integrate import simps

from tacoma.power_law_fitting import fit_power_law_clauset

from _tacoma import flockwork_P_varying_rates
from tacoma import _get_raw_temporal_network

import tacoma as tc


def flockwork_P_equilibrium_group_size_distribution(N, P):
    """Get the equilibrium group size distribution of a Flockwork-P model
    given node number N and probability to reconnect P.

    Parameters
    ----------
    N : int
        Number of nodes
    P : float
        Probability to reconnect

    Returns
    -------
    numpy.ndarray
        Group size distribution of this configuration. The m-th entry
        of this array contains the expected number of nodes of groups
        of size m.
    """

    N = int(N)
    P = float(P)

    assert N > 2
    assert P >= 0.
    assert P <= 1.

    if P == 0.:
        dist = np.zeros((N+1,))
        dist[1] = N
    elif P == 1.:
        dist = np.zeros((N+1,))
        dist[-1] = 1.
    else:
        dist = [N*(1.-P)]

        N_fak = N - np.arange(1, N-1)
        j_fak = (P * np.arange(1, N-1) - N+1.)
        div = N_fak / j_fak
        cum_product_div = np.cumprod(div)
        for m in range(2, N):
            #dist.append( (-1)**(m%2) * float(N)/float(m) * (P-1.) * np.prod(N_fak[1:m]/j_fak[1:m]) * P**(m-1) )
            dist.append((-1)**(m % 2) * float(N)/float(m) *
                        (P-1.) * cum_product_div[m-2] * P**(m-1))

        value = (-1)**(N % 2) * P
        for j in range(1, N-1):
            value *= float(N-j-1) / ((P-N+1.) / P + (j-1))
        #value *= P**(N-1)
        dist.append(value)

        dist = [0.] + dist

    return np.array(dist)


def flockwork_P_equilibrium_configuration(N, P, shuffle_nodes=True, return_histogram=False, seed=0):
    """Get an equilibrium configuration of a Flockwork-P model
    given node number N and probability to reconnect P.

    Parameters
    ----------
    N : int
        Number of nodes
    P : float
        Probability to reconnect
    shuffle_nodes : bool, default : True
        Shuffle the node order in which nodes are distributed
        to groups. 'True' is recommended.
    return_group_size_histogram : bool, default : False
        Return a numpy array containing the counts of groups
        of size :math:`g`.
    seed : int, default : 0
        The random seed. RNG is initialized randomly if ``seed = 0``.
    

    Returns
    -------
    :obj:`list` of :obj:`tuple` of int
        edge list of equilibrium configuration
    numpy.ndarray
        group size counter of this configuration (only
        if ``return_group_size_histogram`` is `True`

    """

    if seed > 0:
        random.seed(seed)

    dist = flockwork_P_equilibrium_group_size_distribution(N, P)

    dist = dist[1:]

    total_group_number = sum(dist)
    size_dist = dist / total_group_number
    num_components = []
    edges = []

    if shuffle_nodes:
        node_ints = random.permutation(N)
    else:
        node_ints = np.arange(N)

    # in the beginning, theres N nodes left
    nodes_left = N

    # ... and no group counter contains any groups yet
    C_m = np.zeros(N)

    # while there are still nodes left to distribute
    while nodes_left > 0:

        # loop through group sizes in descending order.
        # start with the smallest group size that
        # may contain all of the nodes left
        for m in range(nodes_left, 0, -1):

            # if the expected number of groups of this size is not zero
            if dist[m-1] > 0. and nodes_left >= m:

                #new_N_m = random.binomial(total_group_number,size_dist[m-1])
                # dist carries the expected number of m-groups in equilibrium,
                # so we draw a number of m groups from a Poisson distribution
                # with mean dist[m-1]
                new_C_m = random.poisson(dist[m-1])

                # if the new number of groups of size m is larger than the previously drawn number
                if new_C_m > C_m[m-1]:
                    # accept the new number and add the difference in group count of this group size
                    delta_C_m = int(new_C_m - C_m[m-1])
                elif nodes_left == 1 and m == 1:
                    # if there's only one node left, just add it to the loners
                    delta_C_m = 1
                else:
                    delta_C_m = 0

                # add the additional number of groups of this size
                for group_instance in range(delta_C_m):
                    # for u in xrange(nodes_left-1,nodes_left-m,-1):
                    #    for v in xrange(u-1,nodes_left-m-1,-1):
                    #        edges.append((node_ints[u],node_ints[v]))

                    # add fully connected clusters to the edge set
                    if m > 1:
                        edges.extend([(node_ints[u], node_ints[v])
                                      for u in range(nodes_left-1, nodes_left-m, -1)
                                      for v in range(u-1, nodes_left-m-1, -1)])

                    # remove the grouped nodes from the pool of remaining nodes
                    nodes_left -= m

                    # save this group as an accepted group
                    # and increment the group count
                    C_m[m-1] += 1

                    # if there's no nodes left to distribute,
                    # N_m was chosen too large and we abandon
                    if nodes_left <= 0.:
                        break

            # go to next smaller group size

    if return_histogram:
        return edges, np.append(np.array([0.]), C_m)
    else:
        return edges


def flockwork_P_mean_degree_for_varying_rates(flockwork_P_params, N=None):
    """Compute the mean group size distribution for a Flockwork-P system with varying rates.

    Parameters
    ----------
    flockwork_P_params : :obj:`dict`
        Contains all parameters necessary for a Flockwork-P simulation, especially the 
        time-dependent rewiring rate and time-dependent reconnection probability
    N : int, default : None
        If given, compute everything for `N` nodes, where `N` is different from 
        `N` in `flockwork_P_params`.

    Returns
    -------
    t : numpy.array
        An array of times at which the mean degree was evaluated
    k : numpy.array
        An array of mean degree values corresponding to the times in t.
    """

    data = flockwork_P_params

    if N is None:
        N = data['N']

    # compute the initial mean degree
    k0 = 2*len(data['E']) / float(N)

    # get arrays for rewiring
    gamma = np.array(data['rewiring_rate'])
    T, gamma = gamma[:, 0], gamma[:, 1]
    T = np.append(T, data['tmax'])
    gamma = np.append(gamma, gamma[-1])

    P = np.array(data['P'])
    P = np.append(P, P[-1])

    # define the linear ODE describing the mean degree evolution
    def dkdt(t, k, g_, P_):
        return 2 * g_ * P_ - 2*k * (g_*(1-P_))

    # intialize the integrator
    r = ode(dkdt)
    r.set_integrator('dopri5')

    k = [k0]
    new_t = [T[0]]

    i = 0
    for t_, g_, P_ in zip(T[:-1], gamma[:-1], P[:-1]):

        # for every interval set the initial mean degree
        # and new parameters
        r.set_initial_value(k[-1], t_)
        r.set_f_params(g_, P_)

        # for 10 time points within this interval,
        # compute the expected mean degree
        this_t = np.linspace(t_, T[i+1], 10)
        for t__ in this_t[1:]:
            new_t.append(t__)
            this_k = r.integrate(t__)
            k.append(this_k)

        # increase interval
        i += 1

    return np.array(new_t), np.array(k)


def flockwork_P_mean_group_size_distribution_for_varying_rates(flockwork_P_params, N=None):
    """Compute the mean group size distribution for a Flockwork-P system with varying rates.

    Parameters
    ----------
    flockwork_P_params : :obj:`dict`
        Contains all parameters necessary for a Flockwork-P simulation, especially the 
        time-dependent rewiring rate and time-dependent reconnection probability
    N : int, default : None
        If given, compute everything for `N` nodes, where `N` is different from 
        `N` in `flockwork_P_params`.

    Returns
    -------
    mean_distribution : numpy.array
        An array of length `N` with its `i`-th entry containing the mean number of
        groups of size `m = i + 1`.
    """

    if N is None:
        N = flockwork_P_params['N']

    # estimate mean degree from integrating ODE
    new_t, k = flockwork_P_mean_degree_for_varying_rates(flockwork_P_params, N)

    # from equilibrium assumption k = P/(1-P) compute adjusted P
    new_P = k / (k+1)

    distro = []

    # for every time point and adjusted P, compute the equilibrium group size distribution
    for P_ in new_P:
        this_distro = flockwork_P_equilibrium_group_size_distribution(N, P_)
        distro.append(this_distro[1:])

    # compute the mean group size distribution as a time integral over the
    # group size distribution
    distro = np.array(distro)
    mean_distro = np.trapz(distro, x=new_t, axis=0) / (new_t[-1] - new_t[0])

    return mean_distro


def estimated_mean_group_size_distribution(temporal_network):
    """Compute the mean group size distribution for a temporal network under the assumption
    that it can be described reasonably by a flockwork-P model.

    Parameters
    ----------
    temporal_network : :mod:`edge_changes` or :mod:`edge_lists`
        A temporal network.

    Returns
    -------
    mean_distribution : numpy.array
        The average group size distribution of the temporal network which is closer to
        to the _true_ group size distribution than measuring over the binned system.
        The result is an array of length `N` with its `i`-th entry containing the mean number of
        groups of size `m = i + 1`.
    """

    new_t, k = tc.mean_degree(temporal_network)
    N = temporal_network.N

    # from equilibrium assumption k = P/(1-P) compute adjusted P
    new_P = k / (k+1)

    distro = []

    # for every time point and adjusted P, compute the equilibrium group size distribution
    for P_ in new_P:
        this_distro = flockwork_P_equilibrium_group_size_distribution(N, P_)
        distro.append(this_distro[1:])

    # compute the mean group size distribution as a time integral over the
    # group size distribution
    distro = np.array(distro)
    mean_distro = np.trapz(distro, x=new_t, axis=0) / (new_t[-1] - new_t[0])

    return mean_distro


def flockwork_P_mean_group_size_distribution_from_mean_degree_distribution(flockwork_P_params, dk, N=None):
    r"""Compute the mean group size distribution for a Flockwork-P system with varying rates from the 
    mean degree distribution which is fitted as :math:`\left\langle k\right\rangle^{-\alpha}`,
    hence this returns

    .. math::

        \left\langle N_m \right\rangle = \int dk P(k)  \times N_m( k/(k+1) )

    Parameters
    ----------
    flockwork_P_params : :obj:`dict`
        Contains all parameters necessary for a Flockwork-P simulation, especially the 
        time-dependent rewiring rate and time-dependent reconnection probability
    dk : float
        resolution of <k>-space for the solution of the integral.
    N : int, default : None
        If given, compute everything for `N` nodes, where `N` is different from 
        `N` in `flockwork_P_params`.

    Returns
    -------
    mean_distribution : numpy.array
        An array of length `N` with its `i`-th entry containing the mean number of
        groups of size `m = i + 1`.
    """

    if N is None:
        N = flockwork_P_params['N']

    # estimate mean degree from integrating ODE
    new_t, k = flockwork_P_mean_degree_for_varying_rates(flockwork_P_params, N)

    kmin = 2.0 / N
    ind = np.where(k >= kmin)
    new_t = new_t[ind]
    k = k[ind]

    alpha, err, xmin = fit_power_law_clauset(k)
    kmin = k.min()
    kmax = k.max()

    norm = 1/(1-alpha) * (kmax**(-alpha+1) - kmin**(-alpha+1))

    def dist(k_): return k_**(-alpha) / norm

    k = np.linspace(kmin, kmax, int((kmax-kmin) / dk) + 1)

    # from equilibrium assumption k = P/(1-P) compute adjusted P
    new_P = k / (k+1)

    distro = []

    # for every time point and adjusted P, compute the equilibrium group size distribution
    for P_ in new_P:
        this_distro = flockwork_P_equilibrium_group_size_distribution(N, P_)
        distro.append(this_distro[1:])

    distro = np.array(distro)

    mean_distro = simps(dist(k)[:, None] * distro, x=k, axis=0)

    return mean_distro


def flockwork_P(N, P, t_run_total, initial_edges = None, seed = 0, return_edge_changes_with_histograms=False):
    r"""
    Simulate a flockwork P-model where the disconnection rate is 
    :math:`\gamma=1` and reconnection probability is :math:`P`.
    In order to start with an equilibrated initial state, use
    :func:`tacoma.flockwork.flockwork_P_equilibrium_configuration`
    or just pass ``initial_edges = None`` to this function.

    Parameters
    ----------
    N : int
        number of nodes
    P : float
        The reconnection probability. Has to be :math:`0\leq P\leq 1`
    t_run_total : float
        The total run time in units of :math:`\gamma^{-1}=1`.
    initial_edges : list of tuple of int
        The initial state of the network as an edge list.
        If `None` is provided, the initial state will be taken
        from an equilibrium configuration generated with
        :func:`tacoma.flockwork.flockwork_P_equilibrium_configuration`
    seed : int, default : 0
        The random seed.
    return_edge_changes_with_histograms : bool, default : False
        Instead of the converted :class:`_tacoma.edge_changes`,
        return the original instance of 
        :class:`_tacoma.edge_changes_with_histograms`.

    Returns
    -------
    :class:`_tacoma.edge_changes`
        The simulated network. if return_edge_changes_with_histograms is `True`,
        returns an instance of :class:`_tacoma.edge_changes_with_histograms` instead.

    """

    if initial_edges is None:
        initial_edges = flockwork_P_equilibrium_configuration(N, P)

    Ps = [ P ]
    rewiring_rate = [ (0.0, 1.0) ]
    tmax = t_run_total

    fw = flockwork_P_varying_rates(
                                    initial_edges,
                                    N,
                                    Ps,
                                    t_run_total,
                                    rewiring_rate,
                                    tmax,
                                    use_random_rewiring=False,
                                    seed=seed
                                  )

    if not return_edge_changes_with_histograms:
        fw = _get_raw_temporal_network(fw)

    return fw

if __name__ == "__main__":

    N = 10
    P = 0.5

    dist = flockwork_P_equilibrium_group_size_distribution(N, P)

    print(dist, sum([m * h for m, h in enumerate(dist)]))

