import copy
import re
import logging

import numpy as np

from kynetix import ModelShell
from kynetix.functions import *
from kynetix.errors.error import *
from kynetix.database.elements_data import *


class ParserBase(ModelShell):
    '''
    class to operate and analyse rxn equations and rxn lists.
    '''
    def __init__(self, owner):
        """
        A class acts as a base class to be inherited by other
        parser classes, it is not functional on its own.
        """
        #super(self.__class__, self).__init__(owner)
        ModelShell.__init__(self, owner)

        # Set elementary parse regex(compiled)
        self.__regex_dict = {}

        states_regex = re.compile(r'([^\<\>]*)(?:\<?\-\>)' +
                                  r'(?:([^\<\>]*)(?:\<?\-\>))?([^\<\>]*)')
        self.__regex_dict['IS_TS_FS'] = [states_regex, ['IS', 'TS', 'FS']]

        species_regex = re.compile(r'(\d*)([^\_\+\*\<\>]+)_(\d*)(\w+)')
        self.__regex_dict['species'] = \
            [species_regex, ['stoichiometry', 'name', 'site_number', 'site']]

        site_regex = re.compile(r'(\d*)(?:\*\_)(\w+)')
        self.__regex_dict['empty_site'] = [site_regex, ['stoichiometry', 'site']]

        # Parser's species definition
        # NOTE: parser's species definitions is the reference of model's.
        self.__species_definitions = owner._KineticModel__species_definitions

        # Set logger.
        self.__logger = logging.getLogger("model.parser.ParserBase")

    def __check_conservation(self, states_dict):
        """
        Private function to check chemical equation conservation.
        Expect a state dict generated by parse_single_elementary_rxn(),
        check mass conservation for a single equation.
        """
        if not states_dict['TS']:
            states_list = ['IS', 'FS']
            state_elements_list = []
            state_site_list = []
            for state in states_list:
                #get element dict
                elements_sum_dict = \
                    self.__get_elements_num_dict(states_dict[state]['species_dict'])
                state_elements_list.append(elements_sum_dict)
                #get site dict
                total_site_dict = self.__get_total_site_dict(states_dict[state])
                state_site_list.append(total_site_dict)

            if state_elements_list[0] != state_elements_list[1]:
                return 'mass_nonconservative'
            if state_site_list[0] != state_site_list[1]:
                return 'site_nonconservative'
        else:
            states_list = ['IS', 'TS', 'FS']
            state_elements_list = []
            state_site_list = []
            for state in states_list:
                #get element dict
                elements_sum_dict = \
                    self.__get_elements_num_dict(states_dict[state]['species_dict'])
                state_elements_list.append(elements_sum_dict)
                #get site dict
                total_site_dict = self.__get_total_site_dict(states_dict[state])
                state_site_list.append(total_site_dict)

            if not(state_elements_list[0] == state_elements_list[1] ==
                    state_elements_list[2]):
                return 'mass_nonconservative'
            if not(state_site_list[0] == state_site_list[1] ==
                    state_site_list[2]):
                return 'site_nonconservative'

    def __get_total_site_dict(self, state_dict):
        """
        Private function to get site information from a state dict.

        Return:
        -------
        total_site_dict: site information dictionary.

        Example:
        --------
        >>> state_dict =
            {'empty_sites_dict': {'s': {'number': 1, 'type': 's'},
             'species_dict': {'CH-H_s': {'elements': {'C': 1, 'H': 2},
                                         'number': 1,
                                         'site': 's'}},
             'state_expression': 'CH-H_s + *_s'}
        >>> {'s': 2}
        """
        total_site_dict = {}
        if state_dict['empty_sites_dict']:
            for empty_site in state_dict['empty_sites_dict']:
                total_site_dict.setdefault(
                    empty_site,
                    state_dict['empty_sites_dict'][empty_site]['number']
                )

        #get site number from species dict
        for species in state_dict['species_dict']:
            site = state_dict['species_dict'][species]['site']
            # Neglect gas site and liquid site
            if site == 'g' or site == 'l':  
                continue
            site_number = state_dict['species_dict'][species]['site_number']
            sp_number = state_dict['species_dict'][species]['number']
            if site in total_site_dict:
                total_site_dict[site] += sp_number*site_number
            else:
                total_site_dict.setdefault(site, sp_number*site_number)

        return total_site_dict

    def __get_elements_num_dict(self, species_dict):
        """
        Private function to get element number information from speicies_dict.

        Expect a species_dict for a state, e.g.
        {'C_s': {'elements': {'C': 1}, 'number': 1, 'site': 's'},
         'CO_s': {'elements': {'C': 1, 'O': 1}, 'number': 2, 'site': 's'}}
        sum all element number, and return a dict, e.g.
        {'C': 2, 'O': 1}
        """
        sum_element_dict = {}
        for sp in species_dict:
            sp_num = species_dict[sp]['number']
            group = {}
            #generate a dict e.g. group = {'C': 2, 'O': 2}
            for element in species_dict[sp]['elements']:
                group.setdefault(element,
                                 species_dict[sp]['elements'][element]*sp_num)
            sum_element_dict = \
                self.merge_elements_dict(sum_element_dict, group)

        return sum_element_dict

    @staticmethod
    def merge_elements_dict(dict_1, dict_2):
        """
        Merge 2 elements_dict. Add dict_2 to dict_1.
        """
        for element in dict_2:
            if element in dict_1:
                dict_1[element] = dict_1[element] + dict_2[element]
            else:
                dict_1[element] = dict_2[element]

        return dict_1

    def parse_elementary_rxns(self, elementary_rxns):
        """
        Parse all elementary rxn equations by analyse states_dict,

        Return:
        -------
        A tuple of elementary related attributes:
            (adsorbate_names,
             gas_names,
             liquid_names,
             site_names,
             transition_state_names,
             elementary_rxns_list)
        """
        elementary_rxns_list = []
        adsorbate_names = []
        gas_names = []
        liquid_names = []
        site_names = []
        transition_state_names = []

        for equation in self._owner.rxn_expressions():
            # debug info
            self.__logger.debug('parsing [ %s ]', equation)

            states_dict, elementary_rxn = \
                self.parse_single_elementary_rxn(equation)
            #check conservation firstly
            check_result = self.__check_conservation(states_dict)
            if check_result == 'mass_nonconservative':
                raise ValueError('Mass of chemical equation \''+equation +
                                 '\' is not conservative!')
            if check_result == 'site_nonconservative':
                raise ValueError('Site of chemical equation \''+equation +
                                 '\' is not conservative!')
            #analyse state_dict
            for state in states_dict:
                if not states_dict.get(state):
                    continue
                # for transition state, get ts names in addition
                # NOTE: maybe like this -> 'TS': {}
                if state == 'TS' and states_dict.get('TS'):  # ??? need to check '-'?
                    transition_state_names += \
                        states_dict[state]['species_dict'].keys()
                #collect site names
                if states_dict[state].get('empty_sites_dict', None):
                    site_names += states_dict[state]['empty_sites_dict'].keys()
                #collect gas names and adsorbate names
                for sp in states_dict[state]['species_dict']:
                    # If species is gas.
                    if states_dict[state]['species_dict'][sp]['site'] == 'g':
                        gas_names.append(sp)
                    # If species is liquid.
                    elif states_dict[state]['species_dict'][sp]['site'] == 'l':
                        liquid_names.append(sp)
                    elif not '-' in sp:  # sp is adsorbate
                        adsorbate_names.append(sp)
            #merge elementary rxn
            elementary_rxns_list.append(elementary_rxn)

        #merge duplicates in lists
        adsorbate_names = tuple(sorted(list(set(adsorbate_names))))
        gas_names = tuple(sorted(list(set(gas_names))))
        liquid_names = tuple(sorted(list(set(liquid_names))))
        site_names = tuple(sorted(list(set(site_names))))
        transition_state_names = tuple(sorted(list(set(transition_state_names))))
        elementary_rxns_list = elementary_rxns_list

        # Return.
        return (adsorbate_names,
                gas_names,
                liquid_names,
                site_names,
                transition_state_names,
                elementary_rxns_list)

    def parse_single_elementary_rxn(self, equation):
        """
        Parse single reaction equation,

        Parameters:
        -----------
        equation: elementary reaction equation string, str.

        Return:
        -------
        return states dicts of states expressions, like
        states_dict =
        {'TS': {state_expression: 'H-O_s + *_s', 'species_dict': {...}},
         'IS': {}}
        and
        elementary_rxn(list), e.g. [['HCOOH_g', '*_s'], ['HCOOH_s']]

        Example:
        --------
        """
        single_elementary_rxn_list = []

        # begin to parse single equation

        # extract IS, TS, FS expressions
        states_dict = {'IS': {}, 'TS': {}, 'FS': {}}
        m = self.__regex_dict['IS_TS_FS'][0].search(equation)

        for state in self.__regex_dict['IS_TS_FS'][1]:
            idx = self.__regex_dict['IS_TS_FS'][1].index(state)
            if m.group(idx+1):
                states_dict[state]['state_expression'] = m.group(idx+1).strip()
                #analyse state expression
                state_expression = states_dict[state]['state_expression']
                species_dict, empty_sites_dict, state_species_list = \
                    self.__parse_state_expression(state_expression)
                states_dict[state]['species_dict'] = species_dict
                states_dict[state]['empty_sites_dict'] = empty_sites_dict
                single_elementary_rxn_list.append(state_species_list)

        return states_dict, single_elementary_rxn_list

    def __parse_state_expression(self, state_expression):
        """
        Private function to get information from a state expression string.

        Parameter:
        ----------
        state_expression: a state expression string, str.

        Return:
        -------
        An information tuple:
        (species dictionary, site dictionary, species list)

        Example:
        --------
        >>> state_exp = "HCOOH_g + *_s"
        >>> parser._ClassName__parse_state_expression(state_exp)
        >>> {'sp_dict': {'CH-H_s': {'number': 1,
                                    'site': 's',
                                    'elements': {'C': 1, 'H': 2}}}},
            {'s': {'number': 1, 'type': 's'}},
            ['CH2-H_s', '*_s']
        """
        state_dict = {}
        merged_species_list = []
        species_dict, empty_sites_dict = {}, {}
        state_dict['state_expression'] = state_expression
        if '+' in state_expression:
            species_list = state_expression.split('+')
            #strip whitespace in sp_name
            species_list = [raw_sp.strip() for raw_sp in species_list]

            #merge repetitive sp in species_list
            sp_num_dict = {}
            for sp_str in species_list:
                stoichiometry, raw_sp_name = self.split_species(sp_str)
                if raw_sp_name not in sp_num_dict:
                    sp_num_dict.setdefault(raw_sp_name, stoichiometry)
                else:
                    sp_num_dict[raw_sp_name] += stoichiometry
            #convert dict to new merged species_list
            for raw_sp_name in sp_num_dict:
                if sp_num_dict[raw_sp_name] == 1:
                    merged_sp_name = raw_sp_name
                else:
                    merged_sp_name = str(sp_num_dict[raw_sp_name]) + raw_sp_name
                merged_species_list.append(merged_sp_name)
            #Ok! we get a new merged species list

            for sp in merged_species_list:
                if not '*' in sp:
                    species_dict.update(self.__parse_species_expression(sp))
                else:
                    empty_sites_dict.update(self.__parse_site_expression(sp))
        else:
            sp = state_expression.strip()
            #merged_species_list.append(sp)
            species_list = [sp]
            if not '*' in sp:
                species_dict.update(self.__parse_species_expression(sp))
            else:
                empty_sites_dict.update(self.__parse_site_expression(sp))

        return species_dict, empty_sites_dict, species_list

    def __parse_species_expression(self, species_expression):
        """
        Private function to get species info from species string.

        Parse in species expression like '2CH3_s',
        return a sp_dict like
        {'CH3_s': {'number': 2, 'site': 's', 'elements': {'C': 1, 'H':3}}}
        """
        m = self.__regex_dict['species'][0].search(species_expression)
        # match check
        if not m:
            raise SpeciesError('Matching failure for [ %s ]' % species_expression)

        if m.group(1):
            stoichiometry = int(m.group(1))
        else:
            stoichiometry = 1
        species_name = m.group(2)
        if m.group(3):
            site_number = int(m.group(3))
        else:
            site_number = 1
        site = m.group(4)
        if site_number == 1:
            total_name = species_name + '_' + site
        else:
            total_name = species_name + '_' + str(site_number) + site
        #analyse elements
        if '-' in species_name:
            species_name = species_name.replace('-', '')
        elements_list = string2symbols(species_name)
        elements_type_list = list(set(elements_list))
        elements_dict = {}
        for element in elements_type_list:
            elements_dict.setdefault(element,
                                     elements_list.count(element))
        #create sp_dict
        sp_dict = {}
        sp_dict[total_name] = {
            'number': stoichiometry,
            'site': site,
            'site_number': site_number,
            'elements': elements_dict}

        # Update species definitions.
        self.__update_species_definitions(sp_dict)

        return sp_dict

    def __update_species_definitions(self, species_dict):
        """
        Private helper function to update species_definition according species dict.

        Return current species definitions of parser.
        """
        # Check parameter.
        if len(species_dict) != 1:
            msg = "species_dict must have one species, but {} are found.".format(len(species_dict))
            raise ParameterError(msg)

        total_name, = species_dict.keys()
        # Add species to species_defination
        if not total_name in self.__species_definitions:
            self.__species_definitions[total_name] = species_dict[total_name].copy()
            del self.__species_definitions[total_name]['number']
        # Update existed species info.
        else:
            self.__species_definitions[total_name].update(species_dict[total_name])
            del self.__species_definitions[total_name]['number']

        site = species_dict[total_name]["site"]
        # Add species type to species_definition
        if site != 'g' and site != 'l':
            if '-' in total_name:
                self.__species_definitions[total_name]['type'] = 'transition_state'
            else:
                self.__species_definitions[total_name]['type'] = 'adsorbate'
        elif site == 'g':
            self.__species_definitions[total_name]['type'] = 'gas'
        elif site == 'l':
            self.__species_definitions[total_name]['type'] = 'liquid'

        return self.__species_definitions

    def __parse_site_expression(self, site_expression):
        """
        Parse in species expression like '2*_s',
        return a empty_sites_dict like,
        {'s': 'number': 2, 'type': 's'}
        """
        m = self.__regex_dict['empty_site'][0].search(site_expression)
        #['stoichiometry', 'site']
        if m.group(1):
            stoichiometry = int(m.group(1))
        else:
            stoichiometry = 1
        site = m.group(2)
        #create site dict
        empty_sites_dict = {}
        empty_sites_dict[site] = {'number': stoichiometry, 'type': site}

        return empty_sites_dict

    def get_stoichiometry_matrices(self):
        """
        Go through elementary_rxns_list, return sites stoichiometry matrix,
        reactants and products stoichiometry matrix.

        Returns:
        site_matrix: coefficients matrix for intermediates,
                     if species is on the left of arrow, the entry
                     will be positive, vice-versa.
                     row vector: [*, *self.adsorbate_names], numpy.matrix.

        reapro_matrix: coefficients matrix for reactants and product,
                       if species is on the left of arrow, the entry
                       will be positive, vice-versa.
                       row vector: [*self.gas_names], numpy.matrix.
        """
        sites_names = (['*_'+site_name for site_name in self._owner.site_names()] +
                       list(self._owner.adsorbate_names()))
        # reactant and product names
        reapro_names = list(self._owner.gas_names() + self._owner.liquid_names())
        # initialize matrices
        m = len(self._owner.elementary_rxns_list())
        n_s, n_g = len(sites_names), len(reapro_names)
        site_matrix, reapro_matrix = (np.matrix(np.zeros((m, n_s))),
                                      np.matrix(np.zeros((m, n_g))))
        # go through all elementary equations
        for i in xrange(m):
            states_list = self._owner.elementary_rxns_list()[i]
            for sp in states_list[0]:  # for initial state
                stoichiometry, sp_name = self.split_species(sp)
                if sp_name in sites_names:
                    j = sites_names.index(sp_name)
                    site_matrix[i, j] += stoichiometry
                if sp_name in reapro_names:
                    j = reapro_names.index(sp_name)
                    reapro_matrix[i, j] += stoichiometry
            for sp in states_list[-1]:  # for final state
                stoichiometry, sp_name = self.split_species(sp)
                if sp_name in sites_names:
                    j = sites_names.index(sp_name)
                    site_matrix[i, j] -= stoichiometry
                if sp_name in reapro_names:
                    j = reapro_names.index(sp_name)
                    reapro_matrix[i, j] -= stoichiometry

        return site_matrix, reapro_matrix

    def get_total_rxn_equation(self):
        "Get total reaction expression of the kinetic model."
        site_matrix, reapro_matrix = self.get_stoichiometry_matrices()

        def null(A, eps=1e-10):
            "get null space of transposition of site_matrix"
            u, s, vh = np.linalg.svd(A, full_matrices=1, compute_uv=1)
            null_space = np.compress(s <= eps, vh, axis=0)
            return null_space.T
#        def null(A, eps=1e-15):
#            u, s, vh = scipy.linalg.svd(A)
#            null_mask = (s <= eps)
#            null_space = scipy.compress(null_mask, vh, axis=0)
#            return scipy.transpose(null_space)

        x = null(site_matrix.T)  # basis of null space
        if not x.any():  # x is not empty
            raise ValueError('Failed to get basis of nullspace.')
        x = map(abs, x.T.tolist()[0])
        #convert entries of x to integer
        min_x = min(x)
        x = [round(i/min_x, 1) for i in x]
#        setattr(self._owner, 'trim_coeffients', x)
        x = np.matrix(x)
        total_coefficients = (x*reapro_matrix).tolist()[0]

        # cope with small differences between coeffs
        abs_total_coefficients = map(abs, total_coefficients)
        min_coeff = min(abs_total_coefficients)
        total_coefficients = [int(i/min_coeff) for i in total_coefficients]

        # create total rxn expression
        reactants_list, products_list = [], []
        reapro_names = self._owner.gas_names() + self._owner.liquid_names()
        for sp_name in reapro_names:
            idx = reapro_names.index(sp_name)
            coefficient = total_coefficients[idx]
            if coefficient < 0:  # for products
                coefficient = abs(int(coefficient))
                if coefficient == 1:
                    coefficient = ''
                else:
                    coefficient = str(coefficient)
                products_list.append(coefficient + sp_name)
            else:  # for reactants
                coefficient = int(coefficient)
                if coefficient == 1:
                    coefficient = ''
                else:
                    coefficient = str(coefficient)
                reactants_list.append(coefficient + sp_name)

        # get total rxn list and set it as an attr of model
        total_rxn_list = [reactants_list, products_list]
        reactants_expr = ' + '.join(reactants_list)
        products_expr = ' + '.join(products_list)
        total_rxn_equation = reactants_expr + ' -> ' + products_expr

        # check conservation
        states_dict = self.parse_single_elementary_rxn(total_rxn_equation)[0]
        check_result = self.__check_conservation(states_dict)

        if check_result:
            if check_result == 'mass_nonconservative':
                msg = "Mass of total equation '{}' is not conservative.".format(total_rxn_equation)
                raise ValueError(msg)
            if check_result == 'site_nonconservative':
                msg = "Site of total equation '{}' is not conservative.".format(total_rxn_equation)
                raise ValueError(msg)

        # If check passed, return.
        return total_rxn_equation

    # TODO: need to be refactored.
    # below 3 methods are used to merge elementary_rxn_lists
    # NOTE: there is no reaction equation balancing operations
    #       (may add later, if need)
    def get_end_sp_list(self):
        #get sp list and set it as an attr of the model
        end_sp_list = []
        #add site strings
        for site_name in self._owner.site_names:
            site_str = '*_' + site_name
            end_sp_list.append(site_str)
        #add gas names
        end_sp_list.extend(self._owner.gas_names)
        #add adsorbate names
        end_sp_list.extend(self._owner.adsorbate_names)
        self._owner.end_sp_list = end_sp_list

        return end_sp_list

    def get_coefficients_vector(self, elementary_rxn_list):
        """
        Expect a elementary_rxn_list e.g.
        [['HCOOH_s', '*_s'], ['H-COOH_s', '*_s'], ['COOH_s', 'H_s']],
        return corresponding coefficients vector, e.g.
        [1, 0, 0, 0, 0, -1, 1, -1]
        """
        if not hasattr(self._owner, 'end_sp_list'):
            self.get_end_sp_list()
        end_sp_list = self._owner.end_sp_list

        #intialize coefficients vector
        coeff_list = [0]*len(end_sp_list)
        ends_states = (elementary_rxn_list[0], elementary_rxn_list[-1])
        for state_idx, state_list in enumerate(ends_states):
            for sp_str in state_list:
                stoichiometry, species_name = self.split_species(sp_str)
                coeff_idx = end_sp_list.index(species_name)
                if state_idx == 0:
                    coeff = stoichiometry
                else:
                    coeff = -stoichiometry
                #replace corresponding 0 by coeff
                coeff_list[coeff_idx] = coeff

        return np.array(coeff_list)

    def merge_elementary_rxn_list(self, *lists):
        """
        Expect 2 elementary_rxn_list, e.g.
        [['HCOOH_s', '*_s'], ['H-COOH_s', '*_s'], ['COOH_s', 'H_s']]
        and
        [['*_s', 'COOH_s'], ['*_s', 'COO-H_s'], ['CO2_s', 'H_s']],
        return a merged elementary_rxn_list, e.g.
        [['2*_s', 'HCOOH_s'], ['CO2_s', '2H_s']]
        """
        if not hasattr(self._owner, 'end_sp_list'):
            self.get_end_sp_list()
        end_sp_list = self._owner.end_sp_list

        vect_len = len(end_sp_list)
        merged_vect = np.zeros(vect_len)

        for elementary_rxn_list in lists:
            coeff_vect = self.get_coefficients_vector(elementary_rxn_list)
            merged_vect += coeff_vect

        #go through merged_vect to get merged elementary_rxn_list
        left_list, right_list = [], []
        for coeff, sp_name in zip(merged_vect, end_sp_list):
            if coeff > 0:
                if coeff == 1:
                    sp_str = sp_name
                else:
                    sp_str = str(int(coeff)) + sp_name
                left_list.append(sp_str)
            elif coeff < 0:
                coeff = abs(coeff)
                if coeff == 1:
                    sp_str = sp_name
                else:
                    sp_str = str(int(coeff)) + sp_name
                right_list.append(sp_str)

        merged_elementary_rxn_list = [left_list, right_list]

        return merged_elementary_rxn_list

    #methods below are used to find original gas specie of an intermediate
    @staticmethod
    def remove_site_str(state_list):
        """
        Expect a state list e.g. ['2*_s', 'H2O_g'],
        remove site str in it,
        return a new list, e.g. [H2O_g']
        """
        state_list_copy = copy.copy(state_list)
        for sp_str in state_list_copy:
            if '*' in sp_str:
                state_list_copy.remove(sp_str)
        return state_list_copy

    def strip_sp_list(self, sp_list):
        "Remove stoichiometry of species in sp_list."
        striped_sp_list = []
        for sp_str in sp_list:
            stoichiometry, sp_name = self.split_species(sp_str)
            striped_sp_list.append(sp_name)

        return striped_sp_list

    def find_parent_species(self, sp_name):
        """
        Expect a rxns_list e.g.
        [[['*_s', 'HCOOH_g'], ['HCOOH_s']],
        [['HCOOH_s', '*_s'], ['*_s', 'HCO-OH_s'], ['HCO_s', 'OH_s']],
        [['HCO_s', '*_s'], ['*_s', 'H-CO_s'], ['CO_s', 'H_s']],
        [['H_s', 'OH_s'], ['H-OH_s', '*_s'], ['2*_s', 'H2O_g']],
        [['CO_s'], ['CO-_s'], ['*_s', 'CO_g']],
        [['H2O_s'], ['*_s', 'H2O_g']]],
        and a species name, e.g. 'H_s',
        return a list of its parent species, e.g. ['HCO_s']
        """
        parent_list = []
        rxns_list = self._owner.elementary_rxns_list
        for rxn_list in rxns_list:
            FS_sp_list = self.strip_sp_list(rxn_list[-1])
            if sp_name in FS_sp_list:
                parent_list.extend(self.remove_site_str(rxn_list[0]))

        return parent_list

    def find_origin_species(self, sp_name):
        "Find original species which is a gas species of the sp_name."
        parent_list = self.find_parent_species(sp_name)
        if len(parent_list) != 1:
            raise ValueError('%s has two parents: %s!' %
                             (sp_name, str(parent_list)))
        else:
            parent_species_str = parent_list[0]
            parent_species = self.split_species(parent_species_str)[-1]

        while parent_species not in self._owner.gas_names:
            sp_name = parent_species
            parent_list = self.find_parent_species(parent_species)
            if len(parent_list) != 1:
                raise ValueError('%s has two parents: %s!' %
                                 (sp_name, str(parent_list)))
            else:
                parent_species_str = parent_list[0]
                parent_species = self.split_species(parent_species_str)[-1]

        return parent_species  # origin species

    #original gas specie finding END

    #get related species and coefficients in all elementary rxns
    def get_related_adsorbates_wrt_product(self, product_name):
        """
        Expect a product name, return related adsorbate_names wrt the product.

        example:
        --------
        >>> m.parser.get_related_adsorbates('H2O_g')
        >>> {'H_s': 1, 'OH_s': 1}
        """
        #get corresponding adsorbate name
        product_ads = product_name.split('_')[0] + '_s'
        candidate_adsorbates = self.find_parent_species(product_ads)
        if len(candidate_adsorbates) <= 1:
            return {}
        else:  # firstly related adsorbates number must be larger than 1
            origin_sp_list = []
            related_adsorbates_dict = {}
            for sp_str in candidate_adsorbates:
                stoichiometry, sp_name = self.split_species(sp_str)
                related_adsorbates_dict.setdefault(sp_name, stoichiometry)
                #get origin species for sp_name
                origin_sp = self.find_origin_species(sp_name)
                origin_sp_list.append(origin_sp)
            origin_sp_set = set(origin_sp_list)
            if len(origin_sp_set) != 1:
                return {}
            else:
                return related_adsorbates_dict

    def get_related_adsorbates(self):
        """
        Get related adsorbate in all elementary rxns,
        related means there is a certain proportion relations
        among the coverages of these adsorbates.
        """
        if not hasattr(self._owner, 'total_rxn_list'):
            self.get_total_rxn_equation()
        products = self.strip_sp_list(self._owner.total_rxn_list[-1])
        related_adsorbates = []
        for product in products:
            single_related_ads_dict = \
                self.get_related_adsorbates_wrt_product(product)
            related_adsorbates.append(single_related_ads_dict)
        self._owner.related_adsorbates = related_adsorbates
        #get related adsorbates names
        related_adsorbate_names = []
        for rel_ads_dict in self._owner.related_adsorbates:
            if rel_ads_dict:
                keys_tup = tuple(sorted(rel_ads_dict.keys()))
                related_adsorbate_names.append(keys_tup)
        self._owner.related_adsorbate_names = related_adsorbate_names

        return related_adsorbates

    def get_molecular_mass(self, species_name, absolute=False):
        '''
        Function to get relative/absolute molecular mass.

        Parameters:
        -----------
        species_name: name of the molecule species, str.

        absolute: return absolute mass or not(default), bool.

        Example:
        --------
        >>> m.parser.get_molecular_mass('CH4')
        >>> 16.04246
        >>> m.parser.get_molecular_mass('CH4', absolute=True)
        >>> 2.6639131127638393e-26
        '''
        elements = string2symbols(species_name)

        # get molecular total relative mass
        molecular_mass = 0.0
        for element in elements:
            if not element in chem_elements:
                msg = 'Element [ %s ] not in database' % element
                raise ElementSearchingError(msg)
            element_mass = chem_elements[element]['mass']
            molecular_mass += element_mass

        if absolute:
            return amu*molecular_mass
        else:
            return molecular_mass

    def get_relative_energies(self, elementary_rxn_list):
        """
        Function to get relative energies:
            forward barrier,
            reverse barrier,
            reaction energy

        Parameters:
        -----------
        elementary_rxn_list: elementary reaction in list format.

        Returns:
        --------
        f_barrier: forward barrier.
        r_barrier: reverse barrier.
        reaction_energy: reaction energy.
        """
        # Check.
        if not self._owner.has_absolute_energy():
            raise AttributeError("Absolute energie are needed for getting barriers.")

        # Get free energy for states
        G_IS, G_TS, G_FS = 0.0, 0.0, 0.0

        species_definitions = self._owner.species_definitions()

        # Inner function to get species energy.
        def get_species_energy(species_name):
            # Extract site type.
            if "*" in species_name:
                regex = self.__regex_dict["empty_site"][0]
                m = regex.search(species_name)
                species_name = m.groups()[-1]

            return species_definitions[species_name]["formation_energy"]

        # IS energy.
        for sp in elementary_rxn_list[0]:
            stoichiometry, species_name = self.split_species(sp)
            species_energy = get_species_energy(species_name)
            G_IS += stoichiometry*species_energy

        # FS energy.
        for sp in elementary_rxn_list[-1]:
            stoichiometry, species_name = self.split_species(sp)
            species_energy = get_species_energy(species_name)
            G_FS += stoichiometry*species_energy

        # TS energy.
        if len(elementary_rxn_list) == 2:
            G_TS = max(G_IS, G_FS)

        if len(elementary_rxn_list) == 3:
            for sp in elementary_rxn_list[1]:
                stoichiometry, species_name = self.split_species(sp)
                species_energy = get_species_energy(species_name)
                G_TS += stoichiometry*species_energy

        # Get relative energies.
        f_barrier = G_TS - G_IS
        r_barrier = G_TS - G_FS
        reaction_energy = G_FS - G_IS

        return f_barrier, r_barrier, reaction_energy

    def get_relative_from_absolute(self):
        """
        Function to set relative energies from absolute energies.

        """
        Gafs, Gars, dGs = [], [], []

        for rxn_list in self._owner.elementary_rxns_list():
            Gaf, Gar, dG = self.get_relative_energies(rxn_list)
            Gafs.append(Gaf)
            Gars.append(Gar)
            dGs.append(dG)

        relative_energies = dict(Gar=Gars, Gaf=Gafs, dG=dGs)

        return relative_energies

    def regex_dict(self):
        """
        Query function for regress expression dictionary.
        """
        return self.__regex_dict

    @return_deepcopy
    def species_definitions(self):
        """
        Query function for parser's species definitions.
        """
        # Use deep copy to avoid modification of the model's attribution.
        return self.__species_definitions
