import time
import os.path
import tables
from numpy import array, ndarray, int32, float32
from datetime import datetime

# Column types
Int = tables.Int32Col()
IntN = tables.Int32Col #e.g. IntN(shape=(2,3))
Int16 = tables.Int16Col()
Int16N = tables.Int16Col
Float = tables.Float32Col()
FloatN = tables.Float32Col
Double = tables.Float64Col()
DoubleN = tables.Float64Col
String32 = tables.StringCol(32)
StringN = tables.StringCol
Time = tables.Time64Col()
Bool = tables.BoolCol()

# Array types
IntArray = array([], dtype=int32)
FloatArray = array([], dtype=float32)

ExperimentGroup = tables.group
ProtocolGroup = tables.group

"""Persistent Format And Database Operations"""


class Persistor(object):
    """Database helper class"""
    
    h5file = None

    def create_database(self, 
                        filename, 
                        animal_id,
                        session_number,
                        rig,
                        user,
                        experiment_notes,
                        voyeur_version,
                        usercode_version,
                        arduino_protocol_name,
                        user_protocol_name,
                        start_date,
                        timezone,
                        user_metadata):
        """Creates an HDF5 database and defines metadata"""    
        if os.path.splitext(filename)[-1] == 'h5':
            filename = os.path.splitext(filename)[0]
        self.h5file = tables.openFile(filename + ".h5", mode = "w")
        #group_name = 'animal' + str(animal_id) + '_session' + str(animal_id)
        session_group = self.h5file.root #createGroup("/", group_name, user_metadata)
        session_group._v_attrs.animal_id = animal_id
        session_group._v_attrs.rig = rig
        session_group._v_attrs.user = user
        session_group._v_attrs.experiment_notes = experiment_notes
        session_group._v_attrs.voyeur_version = voyeur_version
        session_group._v_attrs.usercode_version = usercode_version
        session_group._v_attrs.arduino_protocol_name = arduino_protocol_name
        session_group.user_protocol_name = user_protocol_name
        session_group._v_attrs.start_date = start_date
        session_group._v_attrs.timezone = timezone
        self.h5file.flush()
        return session_group

    def create_trials(self, 
                    protocol_parameters_definition,
                    controller_parameters_definition,
                    event_definition,
                    session_group,
                    description):
            """Creates trial"""
            
            trial_columns_definition = dict(protocol_parameters_definition.items() 
                                        + strip_tuple_from_dict(controller_parameters_definition).items()
                                        + strip_tuple_from_dict(event_definition).items())
            
            self.h5file.createTable(session_group,
                                    'Trials',
                                    trial_columns_definition,
                                    description)
 
            self.h5file.flush()
            
    def add_trial(self,
                    trial_number,
                    protocol_parameters,
                    controller_parameters,
                    stream_definition,
                    session_group,
                    description):
        """Add a trial"""
        
        trial_group = self.h5file.createGroup(session_group,
                                                "Trial" + str(trial_number).zfill(4),
                                                description)
        
        stream_def = strip_tuple_from_dict(stream_definition)
        if stream_def is not None:
            for name, kind in stream_def.items():
                if type(kind).__name__ == 'ndarray':
                    if kind.dtype == int32:
                        self.create_VLIntArray(name, IntArray, trial_group)
                    elif kind.dtype == float32:
                        self.create_VLFloatArray(name, FloatArray, trial_group)
                    del stream_def[name]
        
        if (stream_def is not None) and len(stream_def) != 0:
            self.h5file.createTable(trial_group,
                                    'Events',
                                    stream_def,
                                    "Stream Data",
                                    chunkshape = 256)
                                    
        #print protocol_parameters
        #print strip_tuple_from_dict(controller_parameters)
        trial_parameters = dict(protocol_parameters.items() 
                                + strip_tuple_from_dict(controller_parameters).items())
        #print trial_parameters
        parameters = session_group.Trials.row
        trial_group._v_attrs.trialIndex = len(session_group.Trials)
        #print parameters
        for key, value in trial_parameters.items():
            #print key, value
            parameters[key] = value
        parameters.append()
        session_group.Trials.flush()                        
                                    
        self.h5file.flush()
        return trial_group
        
    def insert_event(self, event, trial_group):
        """Inserts event values"""
        rowindex = trial_group.Trials.nrows-1
        row = trial_group.Trials[rowindex]

        for key, value in event.iteritems():
            row[key] = value
        
        trial_group.Trials.modifyRows(start=rowindex, stop=rowindex+1, rows=row)
        trial_group.Trials.flush()
        """for index in range(trial_group.Trials.nrows):
            print trial_group.Trials[index]"""
            

        self.h5file.flush()        

    def insert_stream(self, stream, trial_group):
        """Inserts stream data values"""
        row = trial_group.Events.row
        for key, value in stream.iteritems():
            if type(value) == ndarray:
                array = self.h5file.getNode(trial_group, key)
                array.append(value)
            elif value is None:
                continue
            else:
                #row = trial_group.Events.row
                row[key] = value
        row.append()
        trial_group.Events.flush()
        self.h5file.flush()

    def store_array(self, name, description, array, group):
        """Stores a homogenous array in a group"""
        self.h5file.createArray(group, name, array, description)

    def create_VLIntArray(self, name, array, group):
        """Stores a homogenous variable length integer array in a group"""
        self.h5file.createVLArray(group,
                                    name,
                                    tables.Int32Atom(),
                                    "ragged array of ints",
                                    chunkshape = 512)

    def create_VLFloatArray(self, name, array, group):
        """Stores a homogenous variable length float array in a group"""
        self.h5file.createVLArray(group,
                                    name,
                                    tables.Float32Atom(),
                                    "ragged array of floats",
                                    chunkshape = 512)
                                                                    
    def open_database(self, name, mode):
        """Open HDF5 database"""
        if not self.h5file.isopen:
            if os.path.splitext(name)[-1] == 'h5':
                name = os.path.splitext(name)[0]
            self.h5file = tables.openFile(name + ".h5", mode = mode)
                    
    def close_database(self):
        self.h5file.close()

    def timestamp(self):
        """Creates a UTC timestamp"""
        return time.mktime(datetime.utcnow().timetuple())

    def protocol_parameters_definition(self, prot_grp):
        """Get the protocol parameters definition (column types) for given protocol groups"""
        return prot_grp.ProtocolParameters.coltypes

    def controller_parameters_definition(self, prot_grp):
        """Get the controller parameters definition (column types) for given protocol groups"""
        return prot_grp.ControllerParameters.coltypes
    
    def trial_controller_parameters(self, trial_grp):
        """Get the parameters for the trial group from its protocol.ControllerParameters table"""
        protocol = trial_grp._v_parent
        return protocol.ControllerParameters[trial_grp._v_attrs.trialIndex]

    def trial_protocol_parameters(self, trial_grp):
        """Get the parameters for the trial group from its protocol.ProtocolParameters table"""
        protocol = trial_grp._v_parent
        return protocol.ProtocolParameters[trial_grp._v_attrs.trialIndex]
    
    def database_file(self):
        """Path to h5file. None if no database has been created."""
        if self.h5file == None:
            return None
        return self.h5file.filename


def strip_tuple_from_dict(dict):
    """ Calls the correct tuple stripper"""
    if dict:
        values = dict.values()
        if isinstance(values[0], tables.Col):
            return dict
        elif len(values[0]) == 2:
            return strip_2tuple_from_dict(dict)
        elif len(values[0]) == 3:
            return strip_3tuple_from_dict(dict)

        
def strip_2tuple_from_dict(dict):
    """
    Strips the first value of the tuple out of a dictionary
    {key: (first, second)} => {key: second}
    """
    new_dict = {}
    for key, (first, second) in dict.items(): 
        new_dict[key] =  second
    return new_dict
    
    
def strip_3tuple_from_dict(dict):
    """
    Strips the first and second values of the tuple out of a dictionary
    {key: (first, second, third)} => {key: third}
    """
    new_dict = {}
    for key, (first, second, third) in dict.items(): 
        new_dict[key] =  third
    return new_dict
