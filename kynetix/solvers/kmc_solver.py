import logging
import time
from math import exp

try:
    from KMCLib import *
except ImportError:
    print "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
    print "!!!                                                   !!!"
    print "!!!          WARNING: KMCLib is not installed         !!!"
    print "!!! Any kMC calculation using KMCLib will be disabled !!!"
    print "!!!                                                   !!!"
    print "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"

import kynetix.descriptors.descriptors as dc
from kynetix import __version__
from kynetix.errors.error import *
from kynetix.database.thermo_data import kB_eV
from kynetix.database.lattice_data import *
from kynetix.parsers.rxn_parser import *
from kynetix.parsers.parser_base import ParserBase
from kynetix.solvers.solver_base import SolverBase
from kynetix.utilities.profiling_utitlities import do_cprofile
from kynetix.utilities.check_utilities import check_process_dict


class KMCSolver(SolverBase):
    def __init__(self, owner):
        """
        Class for kinetic Monte Carlo simulation.
        """
        super(KMCSolver, self).__init__(owner)

        # set logger
        self.__logger = logging.getLogger('model.solvers.KMCSolver')

        # scripting header
        self.__script_header = (
            '# This file was automatically generated by Kynetix' +
            ' (https://github.com/PytLab/Kynetix) powered by KMCLibX.\n' +
            '# Version {}\n# Date: {} \n#\n' +
            '# Do not make changes to this file ' +
            'unless you know what you are doing\n\n').format(__version__, time.asctime())

        # Set process reaction mapping.
        self.__process_mapping = []

    def run(self,
            scripting=True,
            trajectory_type="lattice"):
        """
        Run the KMC lattice model simulation with specified parameters.

        Parameters:
        -----------
        scripting: generate lattice script or not, True by default, bool.

        trajectory_type: The type of trajectory to use, the default type is "lattice", str.
                         "xyz" | "lattice".

        """
        # {{{
        # Get analysis.
        analysis_name = self._owner.analysis
        if analysis_name:
            analysis = []
            for classname in analysis_name:
                _module = __import__('kmc_plugins', globals(), locals())
                analysis_object = getattr(_module, classname)(self._owner)
                analysis.append(analysis_object)
        else:
            analysis = None

        # Get interactions.
        interactions = KMCInteractions(processes=self.processes,
                                       implicit_wildcards=True)

        # Get configuration.
        configuration = self._owner.configuration

        # Get sitesmap.
        sitesmap = self._owner.sitesmap

        # Construct KMCLatticeModel object.
        model = KMCLatticeModel(configuration=configuration,
                                sitesmap=sitesmap,
                                interactions=interactions)

        if scripting:
            if self._owner.log_allowed:
                self.script_lattice_model(model, script_name='kmc_model.py')
                self.__logger.info('script auto_kmc_model.py created.')

        # Get KMCControlParameters.
        control_parameters = self.get_control_parameters()

        # Get trajectory file name.
        trajectory_filename = "auto_{}_trajectory.py".format(trajectory_type)

        # Run KMC main loop.
        if self._owner.log_allowed:
            self.__logger.info("")
            self.__logger.info("Entering KMCLibX main kMC loop...")

        model.run(control_parameters=control_parameters,
                  trajectory_filename=trajectory_filename,
                  trajectory_type=trajectory_type,
                  analysis=analysis)
        # }}}

    def get_processes(self):
        all_processes = []
        process_dicts = self._owner.process_dicts
        for process_dict in process_dicts:
            processes = self.__get_single_process(process_dict)
            all_processes.extend(processes)

        return all_processes

    def __get_single_process(self, process_dict):
        """
        Private helper function to convert a process dict to KMCLibProcess object.
        """
        # {{{
        # Check process dict.
        process_dict = check_process_dict(process_dict)

        # Check if reaction in rxn_expressions.
        rxn_expressions = self._owner.rxn_expressions

        if process_dict["reaction"] not in rxn_expressions:
            msg = "'{}' is not in model's rxn_expressions.".format(process_dict["reaction"])
            raise SetupError(msg)

        # Check if the elements are in possible elements.
        all_elements = process_dict["elements_before"] + process_dict["elements_after"]
        possible_elements = self._owner.possible_element_types
        for element in all_elements:
            if element not in possible_elements:
                msg = "Element '{}' in process not in possible types {}"
                msg = msg.format(element, possible_elements)
                raise SetupError(msg)

        # Get rate constants.
        rf, rr = self._get_rxn_rates(process_dict["reaction"])

        # Get process fast flag, False by default.
        fast = process_dict.get("fast", False)

        # Get process redist flag, Falst by default.
        redist = process_dict.get("redist", False)

        # Get process redist species.
        redist_species = process_dict.get("redist_species", None)

        # Get KMCLibProcess objects.
        processes = []

        for basis_site in process_dict["basis_sites"]:
            for coordinates in process_dict["coordinates_group"]:
                if self._owner.log_allowed:
                    self.__logger.info("Coordinates = {}".format(coordinates))
                    self.__logger.info("Basis site = {}".format(basis_site))

                # Forward process.
                fprocess = KMCProcess(coordinates=coordinates,
                                      elements_before=process_dict["elements_before"],
                                      elements_after=process_dict["elements_after"],
                                      basis_sites=[basis_site],
                                      rate_constant=rf,
                                      fast=fast,
                                      redist=redist,
                                      redist_species=redist_species)
                processes.append(fprocess)

                # Add process reaction mapping.
                if not fast:
                    process_mapping = "{}(->)".format(process_dict["reaction"])
                    self.__process_mapping.append(process_mapping)

                # Info output.
                if self._owner.log_allowed:
                    self.__logger.info("Forward elements changes:")
                    self.__logger.info("    /{}".format(process_dict["elements_before"]))
                    self.__logger.info("    \{}".format(process_dict["elements_after"]))

                # --------------------------------------------------------------
                # NOTE: If the proess is a redistribution process which is only
                #       used to re-scatter the fast species, its reverse process
                #       would not be parsed.
                # --------------------------------------------------------------

                # Reverse process.
                if not redist:
                    rprocess = KMCProcess(coordinates=coordinates,
                                          elements_before=process_dict["elements_after"],
                                          elements_after=process_dict["elements_before"],
                                          basis_sites=[basis_site],
                                          rate_constant=rr,
                                          fast=fast)
                    processes.append(rprocess)

                # Add process reaction mapping.
                if not fast:
                    process_mapping = "{}(<-)".format(process_dict["reaction"])
                    self.__process_mapping.append(process_mapping)

                # Info output.
                if not redist and self._owner.log_allowed:
                    self.__logger.info("Reverse elements changes:")
                    self.__logger.info("    /{}".format(process_dict["elements_after"]))
                    self.__logger.info("    \{}".format(process_dict["elements_before"]))

        if self._owner.log_allowed:
            self.__logger.info("\n")

        return processes
        # }}}

    def _get_rxn_rates(self, rxn_expression):
        """
        Private helper function to get rate constants for an elementary reaction.
        """
        # {{{
        # Get raw relative energies.
        Gaf, Gar, dG = self.__get_relative_energies(rxn_expression)
        if self._owner.log_allowed:
            self.__logger.info("{} (Gaf={}, Gar={}, dG={})".format(rxn_expression, Gaf, Gar, dG))

        # Get reactants and product types.
        rxn_equation = RxnEquation(rxn_expression)
        formula_list = rxn_equation.to_formula_list()
        istate, fstate = formula_list[0], formula_list[-1]
        is_types = [formula.type() for formula in istate]
        fs_types = [formula.type() for formula in fstate]
        if self._owner.log_allowed:
            self.__logger.info("species type: {} -> {}".format(is_types, fs_types))

        # Get rate constant.
        T = self._owner.temperature
        Auc = self._owner.unitcell_area
        act_ratio = self._owner.active_ratio

        # Get model corrector.
        corrector = self._owner.corrector
        # Check.
        if type(corrector) == str:
            msg = "No instantialized corrector, try to modify '{}'"
            msg = msg.format(self._owner.setup_file)
            raise SetupError(msg)

        # Forward rate.

        # Gas participating.
        if "gas" in is_types:
            # Get gas pressure.
            idx = is_types.index("gas")
            formula = istate[idx]
            gas_name = formula.formula()
            p = self._owner.species_definitions[gas_name]["pressure"]

            # Use Collision Theory.
            Ea = Gaf
            m = ParserBase.get_molecular_mass(formula.species(), absolute=True)
            rf = SolverBase.get_kCT(Ea, Auc, act_ratio, p, m, T)
            if self._owner.log_allowed:
                self.__logger.info("R(forward) = {} s^-1 (Collision Theory)".format(rf))
        # No gas participating.
        else:
            # ThermoEquilibrium and gas species in final state.
            if "gas" in fs_types and Gar < 1e-10:
                # Correction energy.
                idx = fs_types.index("gas")
                formula = fstate[idx]
                gas_name = formula.species_site()
                p = self._owner.species_definitions[gas_name]["pressure"]
                m = ParserBase.get_molecular_mass(formula.species(), absolute=True)
                correction_energy = corrector.entropy_correction(gas_name, m, p, T)
                stoichiometry = formula.stoichiometry()
                Gaf += stoichiometry*correction_energy

                # Info output.
                msg = "Correct forward barrier: {} -> {}".format(Gaf-correction_energy, Gaf)
                if self._owner.log_allowed:
                    self.__logger.info(msg)

            rf = SolverBase.get_kTST(Gaf, T)
            if self._owner.log_allowed:
                self.__logger.info("R(forward) = {} s^-1 (Transition State Theory)".format(rf))

        # Reverse rate.

        # Gas participating.
        if "gas" in fs_types:
            # Get gas pressure.
            idx = fs_types.index("gas")
            formula = fstate[idx]
            gas_name = formula.formula()
            p = self._owner.species_definitions[gas_name]["pressure"]

            # Use Collision Theory.
            Ea = Gar
            m = ParserBase.get_molecular_mass(formula.species(), absolute=True)
            rr = SolverBase.get_kCT(Ea, Auc, act_ratio, p, m, T)
            if self._owner.log_allowed:
                self.__logger.info("R(reverse) = {} s^-1 (Collision Theory)".format(rr))
        # No gas participating.
        else:
            # Check if it is an adsorption process.
            if "gas" in is_types and Gaf < 1e-10:
                # Correction energy.
                idx = is_types.index("gas")
                formula = istate[idx]
                gas_name = formula.species_site()
                p = self._owner.species_definitions[gas_name]["pressure"]
                m = ParserBase.get_molecular_mass(formula.species(), absolute=True)
                correction_energy = corrector.entropy_correction(gas_name, m, p, T)
                stoichiometry = formula.stoichiometry()
                dG -= stoichiometry*correction_energy

                # Info output.
                if self._owner.log_allowed:
                    msg = "Correct dG: {} -> {}".format(dG+correction_energy, dG)
                    self.__logger.info(msg)

                # Use Equilibrium condition to get reverse rate.
                K = exp(-dG/(kB_eV*T))
                rr = rf/K
                if self._owner.log_allowed:
                    self.__logger.info("R(reverse) = {} s^-1 (Equilibrium Condition)".format(rr))
            else:
                # Use Transition State Theory.
                rr = SolverBase.get_kTST(Gar, T)
                if self._owner.log_allowed:
                    self.__logger.info("R(reverse) = {} s^-1 (Transition State Theory)".format(rr))

        return rf, rr
        # }}}

    def __get_relative_energies(self, rxn_expression):
        """
        Private helper function to get relative energies for an elementary reaction.
        """
        # Check if parser has relative energies.
        if not self._owner.has_relative_energy:
            msg = "Model has no relative energies, try to use parser to parse data"
            raise AttributeError(msg)

        # Get raw relative energies.
        rxn_expressions = self._owner.rxn_expressions
        idx = rxn_expressions.index(rxn_expression)

        Gaf = self._owner.relative_energies["Gaf"][idx]
        Gar = self._owner.relative_energies["Gar"][idx]
        dG = self._owner.relative_energies["dG"][idx]

        return Gaf, Gar, dG

    def get_control_parameters(self):
        """
        Function to get KMCLib KMCControlParameters instance.
        """
        # {{{
        # Get parameters in model.
        time_limit=self._owner.time_limit
        number_of_steps=self._owner.nstep
        dump_interval=self._owner.trajectory_dump_interval
        seed=self._owner.random_seed
        rng_type=self._owner.random_generator
        analysis_interval=self._owner.analysis_interval
        start_time=self._owner.start_time
        extra_traj=self._owner.extra_trajectories
        do_redistribution=self._owner.do_redistribution

        control_params = dict(time_limit=time_limit,
                              number_of_steps=number_of_steps,
                              dump_interval=dump_interval,
                              seed=seed,
                              rng_type=rng_type,
                              analysis_interval=analysis_interval,
                              start_time=start_time,
                              extra_traj=extra_traj,
                              do_redistribution=do_redistribution)

        if do_redistribution:
            redistribution_dict = dict(
                redistribution_interval=self._owner.redistribution_interval,
                fast_species=self._owner.fast_species,
                nsplits=self._owner.nsplits,
                distributor_type=self._owner.distributor_type,
                empty_element=self._owner.empty_type
            )
            control_params.update(redistribution_dict)

        # KMCLib control parameter instantiation
        control_parameters = KMCControlParameters(**control_params)

        return control_parameters
        # }}}

    #-----------------------
    # script KMCLib objects |
    #-----------------------

    def script_decorator(func):
        '''
        Decorator for KMCLib objects scripting.
        Add some essential import statements and save operation.
        '''
        def wrapper(self, obj, script_name=None):
            content = self.__script_header + 'from KMCLib import *\n\n'
            content += func(self, obj)

            # write to file
            if script_name:
                script_name = 'auto_' + script_name
                with open(script_name, 'w') as f:
                    f.write(content)
                if self._owner.log_allowed:
                    self.__logger.info('interactions script written to %s', script_name)

            return content

        return wrapper

    @script_decorator
    def script_lattice_model(self, lattice_model):
        """
        Generate a script representation of lattice model instances.

        Parameters:
        -----------
        lattice_model: The KMCLatticeModel object.

        script_name: filename into which script written, str.
                     set to None by default and no file will be generated.

        Returns:
        --------
        A script that can generate this lattice model object, str.

        """
        content = lattice_model._script()

        return content

    @script_decorator
    def script_configuration(self, configuration):
        '''
        Generate a script representation of interactions instances.

        Parameters:
        -----------
        configuration: The KMCConfiguration object.

        script_name: filename into which script written, str.
                     set to None by default and no file will be generated.

        Returns:
        --------
        A script that can generate this configuration object, str.

        '''
        content = configuration._script()

        return content

    @script_decorator
    def script_interactions(self, interactions):
        '''
        Generate a script representation of interactions instances.

        Parameters:
        -----------
        interactions: The KMCInteractions object.

        script_name: filename into which script written, str.
                     set to None by default and no file will be generated.

        Returns:
        --------
        A script that can generate this interactions object, str.

        '''
        content = interactions._script()

        return content

    @script_decorator
    def script_processes(self, processes):
        '''
        Generate a script representation of processes instances.

        Parameters:
        -----------
        processes: A list of KMCProcess object.

        script_name: filename into which script written, str.
                     set to None by default and no file will be generated.

        Returns:
        --------
        A script that can generate this process object, str.

        '''
        # Get content string.
        content = ''
        for idx, proc in enumerate(processes):
            proc_str = proc._script('process_%d' % idx)
            content += proc_str
        # gather processes
        proc_str = 'processes = [\n'
        for idx in xrange(len(processes)):
            proc_str += (' '*4 + 'process_%d,\n' % idx)
        proc_str += ']\n\n'

        content += proc_str

        return content

    @dc.Property
    def processes(self):
        """
        Query function for processes list.
        """
        try:
            return self.__processes
        except AttributeError:
            self.__processes = self.get_processes()
            return self.__processes

    @dc.Property
    def process_mapping(self):
        """
        Query function for process reaction type mapping.
        """
        return self.__process_mapping

