"""
Data handler and main window creator for 3D data inspection
"""
import os
import warnings
from copy import deepcopy

import matplotlib.pyplot as plt
import numpy as np
from data_slicer import pit
from PyQt5.QtWidgets import QMessageBox, QLineEdit
from pyqtgraph.Qt import QtWidgets
from pyqtgraph import InfiniteLine

import piva._2Dviewer as p2d
import piva.working_procedures as wp
import piva.data_loader as dl
import piva.imageplot as ip
from piva._2Dviewer import ORIENTLINES_LINECOLOR, erg_ax, scan_ax
from piva.cmaps import cmaps

import time

slit_ax = 1


class DataHandler3D:
    """ Object that keeps track of a set of 3D data and allows
    manipulations on it. In a Model-View-Controller framework this could be
    seen as the Model, while :class:`MainWindow <data_slicer.pit.MainWindow>`
    would be the View part.
    """

    def __init__(self, main_window):
        self.main_window = main_window
        self.binning = False
        # self.erg_ax = erg_ax

        # Initialize instance variables
        # np.array that contains the 3D data
        self.data = None
        self.axes = np.array([[0, 1], [0, 1], [0, 1]])
        # Indices of *data* that are displayed in the main plot
        self.displayed_axes = (0, 1)
        # Index along the z axis at which to produce a slice
        self.z = ip.TracedVariable(0, name='z')
        # # Number of slices to integrate along z
        # integrate_z = TracedVariable(value=0, name='integrate_z')
        # How often we have rolled the axes from the original setup
        self._roll_state = 0

        # moved to get rid of warnings
        self.zmin = 0
        self.zmax = None
        self.integrated = None
        self.cut_y_data = None
        self.cut_x_data = None

    def get_data(self):
        """ Convenience `getter` method. Allows writing ``self.get_data()``
        instead of ``self.data.get_value()``.
        """
        if self.main_window.util_panel.image_normalize_edcs.isChecked():
            return self.norm_data
        else:
            return self.data.get_value()

    def set_data(self, data):
        """ Convenience `setter` method. Allows writing ``self.set_data(d)``
        instead of ``self.data.set_value(d)``.
        """
        self.data.set_value(data)
        with warnings.catch_warnings():
            self.norm_data = wp.normalize(data)

    def prepare_data(self, data, axes=3 * [None]):
        """ Load the specified data and prepare the corresponding z range.
        Then display the newly loaded data.

        **Parameters**

        ====  ==================================================================
        data  3d array; the data to display
        axes  len(3) list or array of 1d-arrays or None; the units along the
              x, y and z axes respectively. If any of those is *None*, pixels
              are used.
        ====  ==================================================================
        """

        self.data = ip.TracedVariable(data, name='data')
        self.axes = np.array(axes, dtype="object")
        with warnings.catch_warnings():
            self.norm_data = wp.normalize(data)
        self.prepare_axes()
        self.on_z_dim_change()

        # Connect signal handling so changes in data are immediately reflected
        self.z.sig_value_changed.connect(lambda: self.main_window.update_main_plot(emit=False))
        # self.data.sig_value_changed.connect(self.on_data_change)

        self.main_window.update_main_plot()
        self.main_window.set_axes()

    def get_main_data(self):
        """ Return the 2d array that is currently displayed in the main plot.
        """
        return self.main_window.main_plot.image_data

    def get_cut_data(self):
        """ Return the 2d array that is currently displayed in the cut plot.
        """
        return self.main_window.cut_plot.image_data

    def get_hprofile(self):
        """ Return an array containing the y values displayed in the
        horizontal profile plot (mw.y_plot).

        .. seealso::
            :func:`data_slicer.imageplot.CursorPlot.get_data`
        """
        return self.main_window.y_plot.get_data()[1]

    def get_vprofile(self):
        """ Return an array containing the x values displayed in the
        vertical profile plot (mw.x_plot).

        .. seealso::
            :func:`data_slicer.imageplot.CursorPlot.get_data`
        """
        return self.main_window.x_plot.get_data()[0]

    def get_iprofile(self):
        """ Return an array containing the y values displayed in the
        integrated intensity profile plot (mw.integrated_plot).

        .. seealso::
            :func:`data_slicer.imageplot.CursorPlot.get_data`
        """
        return self.main_window.integrated_plot.get_data()[1]

    def update_z_range(self):
        """ When new data is loaded or the axes are rolled, the limits and
        allowed values along the z dimension change.
        """
        # Determine the new ranges for z
        self.zmin = 0
        self.zmax = self.get_data().shape[2]

        self.z.set_allowed_values(range(self.zmin, self.zmax))

    def prepare_axes(self):
        """ Create a list containing the three original x-, y- and z-axes
        and replace *None* with the amount of pixels along the given axis.
        """
        shapes = self.data.get_value().shape
        # Avoid undefined axes scales and replace them with len(1) sequences
        for i, axis in enumerate(self.axes):
            if axis is None:
                self.axes[i] = np.arange(shapes[i])

    def on_data_change(self):
        """ Update self.main_window.image_data and replot. """
        self.update_image_data()
        self.main_window.redraw_plots()
        # Also need to recalculate the intensity plot
        self.on_z_dim_change()

    def on_z_dim_change(self):
        """ Called when either completely new data is loaded or the dimension
        from which we look at the data changed (e.g. through :func:`roll_axes
        <data_slicer.pit.PITDataHandler.roll_axes>`).
        Update the z range and the integrated intensity plot.
        """
        self.update_z_range()

        # Get a shorthand for the integrated intensity plot
        ip = self.main_window.plot_z
        # Remove the old integrated intensity curve
        try:
            old = ip.listDataItems()[0]
            ip.removeItem(old)
        except IndexError:
            pass

        # Calculate the integrated intensity and plot it
        self.calculate_integrated_intensity()
        with warnings.catch_warnings():
            ip.plot(wp.normalize(self.integrated))

        # Also display the actual data values in the top axis
        zscale = self.axes[erg_ax]
        zmin = zscale[0]
        zmax = zscale[-1]
        ip.set_secondary_axis(0, len(zscale))
        ip.set_ticks(zmin, zmax, ip.main_xaxis)

    def calculate_integrated_intensity(self):
        self.integrated = self.get_data().sum(0).sum(0)

    def update_image_data(self):
        """ Get the right (possibly integrated) slice out of *self.data*,
        apply postprocessings and store it in *self.image_data*.
        Skip this if the z value happens to be out of range, which can happen
        if the image data changes and the z scale hasn't been updated yet.
        """
        z = self.z.get_value()
        integrate_z = self.main_window.plot_z.width
        data = self.get_data()
        try:
            self.main_window.image_data = self.make_slice(data, dim=2, index=z, integrate=integrate_z)
        except IndexError:
            pass
        self.main_window.util_panel.energy_main.setValue(z)
        if self.main_window.new_energy_axis is None:
            self.main_window.util_panel.energy_main_value.setText('({:.4f})'.format(self.axes[erg_ax][z]))
        else:
            self.main_window.util_panel.energy_main_value.setText(
                '({:.4f})'.format(self.main_window.new_energy_axis[z]))
        # self.main_window.update_z_binning_lines()

    @staticmethod
    def make_slice(data, dim, index, integrate=0, silent=True):
        """
        Take a slice out of an N dimensional dataset *data* at *index* along
        dimension *dim*. Optionally integrate by +- *integrate* channels around
        *index*.
        If *data* has shape::

            (n0, n1, ..., n(dim-1), n(dim), n(dim+1), ..., n(N-1))

        the result will be of dimension N-1 and have shape::

            (n0, n1, ..., n(dim-1), n(dim+1), ..., n(N-1))

        or in other words::

            shape(result) = shape(data)[:dim] + shape(data)[dim+1:]

        .

        **Parameters**

        =========  =================================================================
        data       array-like; N dimensional dataset.
        dim        int, 0 <= d < N; dimension along which to slice.
        index      int, 0 <= index < data.size[d]; The index at which to create
                   the slice.
        integrate  int, ``0 <= integrate < |index|``; the number of slices above
                   and below slice *index* over which to integrate. A warning is
                   issued if the integration range would exceed the data (can be
                   turned off with *silent*).
        silent     bool; toggle warning messages.
        =========  =================================================================

        **Returns**

        ===  =======================================================================
        res  np.array; slice at *index* alond *dim* with dimensions shape[:d] +
             shape[d+1:].
        ===  =======================================================================
        """
        # Find the dimensionality and the number of slices along the specified dimension.
        shape = data.shape
        ndim = len(shape)
        try:
            n_slices = shape[dim]
        except IndexError:
            message = '*dim* ({}) needs to be smaller than the dimension of *data* ({})'.format(dim, ndim)
            raise IndexError(message)

        # Set the integration indices and adjust them if they go out of scope
        start = index - integrate
        stop = index + integrate + 1
        if start < 0:
            if not silent:
                warnings.warn('i - integrate ({}) < 0, setting start=0'.format(start))
            start = 0
        if stop > n_slices:
            if not silent:
                warning = 'i + integrate ({}) > n_slices ({}), setting stop=n_slices'.format(stop, n_slices)
                warnings.warn(warning)
            stop = n_slices

        # Roll the original data such that the specified dimension comes first
        i_original = np.arange(ndim)
        i_rolled = np.roll(i_original, dim)
        data = np.moveaxis(data, i_original, i_rolled)
        # Take the slice
        sliced = data[start:stop].sum(0)
        # Bring back to more intuitive form. For that we have to remove the now
        # lost dimension from the index arrays and shift all indices.
        i_original = np.concatenate((i_original[:dim], i_original[dim + 1:]))
        i_original[i_original > dim] -= 1
        i_rolled = np.roll(i_original, dim)
        return np.moveaxis(sliced, i_rolled, i_original)

    def lineplot(self, plot='main', dim=0, ax=None, n=10, offset=0.2, lw=0.5,
                 color='k', label_fmt='{:.2f}', n_ticks=5, **getlines_kwargs):
        """
        Create a matplotlib figure with *n* lines extracted out of one of the
        visible plots. The lines are normalized to their global maximum and
        shifted from each other by *offset*.
        See :func:`get_lines <data_slicer.utilities.get_lines>` for more
        options on the extraction of the lines.
        This wraps the :class:`ImagePlot <data_slicer.imageplot.ImagePlot>`'s
        lineplot method.

        **Parameters**

        ===============  =======================================================
        plot             str; either "main" or "cut", specifies from which
                         plot to extract the lines.
        dim              int; either 0 or 1, specifies in which direction to
                         take the lines.
        ax               matplotlib.axes.Axes; the axes in which to plot. If
                         *None*, create a new figure with a fresh axes.
        n                int; number of lines to extract.
        offset           float; spacing between neighboring lines.
        lw               float; linewidth of the plotted lines.
        color            any color argument understood by matplotlib; color
                         of the plotted lines.
        label_fmt        str; a format string for the ticklabels.
        n_ticks          int; number of ticks to print.
        getlines_kwargs  other kwargs are passed to :func:`get_lines
                         <data_slicer.utilities.get_lines>`
        ===============  =======================================================

        **Returns**

        ===========  ===========================================================
        lines2ds     list of Line2D objects; the drawn lines.
        xticks       list of float; locations of the 0 intensity value of
                     each line.
        xtickvalues  list of float; if *momenta* were supplied, corresponding
                     xtick values in units of *momenta*. Otherwise this is
                     just a copy of *xticks*.
        xticklabels  list of str; *xtickvalues* formatted according to
                     *label_fmt*.
        ===========  ===========================================================

        .. seealso::
            :func:`get_lines <data_slicer.utilities.get_lines>`
        """
        # Get the specified data
        if plot == 'main':
            imageplot = self.main_window.main_plot
        elif plot == 'cut':
            imageplot = self.main_window.cut_plot
        else:
            raise ValueError('*plot* should be one of ("main", "cut").')

        # Create a mpl axis object if none was given
        if ax is None:
            fig, ax = plt.subplots(1)

        return imageplot.lineplot(ax=ax, dim=dim, n=n, offset=offset, lw=lw,
                                  color=color, label_fmt=label_fmt,
                                  n_ticks=n_ticks, **getlines_kwargs)


class MainWindow3D(QtWidgets.QMainWindow):

    # TODO bugs
    # TODO plot_z bins not moving when changing slider's position in spinbox
    # TODO cut_x/plot_x width doesn't always match main_plot's

    # TODO utilities
    # TODO logbook!

    def __init__(self, data_browser, data_set=None, index=None, slice=False):
        super(MainWindow3D, self).__init__()
        self.title = index.split('/')[-1]
        self.fname = index
        self.central_widget = QtWidgets.QWidget()
        self.layout = QtWidgets.QGridLayout()

        # moved to get rid of warnings
        self.cmap = None
        self.image_kwargs = None
        self.cmap_name = None
        self.lut = None
        self.db = data_browser
        self.index = index
        self.slice = slice
        self.new_energy_axis = None
        self.kx_axis = None
        self.ky_axis = None
        self.thread = {}
        self.thread_count = 0
        self.data_viewers = {}

        # Initialize instance variables
        # Plot transparency alpha
        self.alpha = 1
        # Plot powerlaw normalization exponent gamma
        self.gamma = 1
        # Relative colormap maximum
        self.vmax = 1

        # Need to store original transformation information for `rotate()`
        self._transform_factors = []

        # Create the 3D (main) and cut ImagePlots
        self.main_plot = ip.ImagePlot(name='main_plot')
        # Create cut plot along x
        self.cut_x = ip.ImagePlot(name='cut_x')
        # Create cut of cut_x
        self.plot_x = ip.CursorPlot(name='plot_x')
        # Create cut plot along y
        self.cut_y = ip.ImagePlot(name='cut_y', orientation='vertical')
        # Create cut of cut_y
        self.plot_y = ip.CursorPlot(name='plot_y', orientation='vertical')
        # Create the integrated intensity plot
        self.plot_z = ip.CursorPlot(name='plot_z', z_plot=True)
        # Create utilities panel
        self.util_panel = ip.UtilitiesPanel(self, name='utilities_panel')

        self.setStyleSheet(p2d.app_style)
        self.set_cmap()

        self.setGeometry(100, 100, 800, 900)
        self.setWindowTitle(self.title)
        self.sp_EDC = None

        if data_set is None:
            print('No dataset to open.')
        else:
            D = data_set

        self.data_handler = DataHandler3D(self)
        self.initUI()

        self.data_set = data_set
        self.org_dataset = None
        self.data_handler.prepare_data(D.data, [D.xscale, D.yscale, D.zscale])
        self.set_sliders_labels(D)

        self.util_panel.energy_main.setRange(0, len(self.data_handler.axes[erg_ax]))
        self.util_panel.energy_hor.setRange(0, len(self.data_handler.axes[erg_ax]))
        self.util_panel.energy_vert.setRange(0, len(self.data_handler.axes[erg_ax]))
        self.util_panel.momentum_hor.setRange(0, len(self.data_handler.axes[slit_ax]))
        self.util_panel.momentum_vert.setRange(0, len(self.data_handler.axes[scan_ax]))
        self.util_panel.orientate_init_x.setRange(0, self.data_handler.axes[scan_ax].size)
        self.util_panel.orientate_init_y.setRange(0, self.data_handler.axes[slit_ax].size)

        # create a single point EDC at crossing point of momentum sliders
        self.sp_EDC = self.plot_z.plot()
        self.set_sp_EDC_data()

        try:
            self.load_saved_corrections(data_set)
        except AttributeError:
            print('going with old settings.')
            self.load_saved_corrections_old(data_set)

        self.put_sliders_in_initial_positions()
        self.set_pmesh_axes()

    def initUI(self):
        self.setWindowTitle(self.title)
        # Create a "central widget" and its layout
        self.central_widget.setLayout(self.layout)
        self.setCentralWidget(self.central_widget)

        # Create cut plot along x
        self.cut_x.register_momentum_slider(self.main_plot.pos[0])
        self.cut_x.crosshair.vpos.sig_value_changed.connect(self.update_cut_y)
        self.cut_x.crosshair.hpos.sig_value_changed.connect(self.update_plot_x)

        # Create cut of cut_x
        self.plot_x.register_traced_variable(self.main_plot.pos[0])

        # Create cut plot along y
        self.cut_y.register_momentum_slider(self.main_plot.pos[1])
        self.cut_y.crosshair.vpos.sig_value_changed.connect(self.update_cut_x)
        self.cut_y.crosshair.hpos.sig_value_changed.connect(self.update_plot_y)

        # Create cut of cut_y
        self.plot_y.register_traced_variable(self.main_plot.pos[1])

        # Create the integrated intensity plot
        self.plot_z.register_traced_variable(self.data_handler.z)
        self.plot_z.change_width_enabled = True

        # Connect signals to utilities panel
        self.util_panel.image_cmaps.currentIndexChanged.connect(self.set_cmap)
        self.util_panel.image_invert_colors.stateChanged.connect(self.set_cmap)
        self.util_panel.image_gamma.valueChanged.connect(self.set_gamma)
        self.util_panel.image_colorscale.valueChanged.connect(self.set_colorscale)
        self.util_panel.image_normalize_edcs.stateChanged.connect(self.update_main_plot)
        self.util_panel.image_show_BZ.stateChanged.connect(self.update_main_plot)
        self.util_panel.image_symmetry.valueChanged.connect(self.update_main_plot)
        self.util_panel.image_rotate_BZ.valueChanged.connect(self.update_main_plot)
        self.util_panel.image_2dv_button.clicked.connect(self.open_2dviewer)

        # binning signals
        self.util_panel.bin_x.stateChanged.connect(self.set_x_binning_lines)
        self.util_panel.bin_x_nbins.valueChanged.connect(self.set_x_binning_lines)
        self.util_panel.bin_y.stateChanged.connect(self.set_y_binning_lines)
        self.util_panel.bin_y_nbins.valueChanged.connect(self.set_y_binning_lines)
        self.util_panel.bin_z.stateChanged.connect(self.update_z_binning_lines)
        self.util_panel.bin_z_nbins.valueChanged.connect(self.update_z_binning_lines)
        self.util_panel.bin_zx.stateChanged.connect(self.set_zx_binning_line)
        self.util_panel.bin_zx_nbins.valueChanged.connect(self.set_zx_binning_line)
        self.util_panel.bin_zy.stateChanged.connect(self.set_zy_binning_line)
        self.util_panel.bin_zy_nbins.valueChanged.connect(self.set_zy_binning_line)

        # sliders signals
        self.util_panel.energy_main.valueChanged.connect(self.set_main_energy_slider)
        self.util_panel.energy_hor.valueChanged.connect(self.set_hor_energy_slider)
        self.util_panel.energy_vert.valueChanged.connect(self.set_vert_energy_slider)
        self.util_panel.momentum_hor.valueChanged.connect(self.set_hor_momentum_slider)
        self.util_panel.momentum_vert.valueChanged.connect(self.set_vert_momentum_slider)
        self.util_panel.bin_x_nbins.setValue(2)
        self.util_panel.bin_y_nbins.setValue(10)
        self.util_panel.bin_z_nbins.setValue(10)
        self.util_panel.bin_zx_nbins.setValue(5)
        self.util_panel.bin_zy_nbins.setValue(5)

        # buttons
        self.util_panel.close_button.clicked.connect(self.close)
        self.util_panel.save_button.clicked.connect(self.save_to_pickle)
        self.util_panel.pit_button.clicked.connect(self.open_pit)

        # energy and k-space concersion
        self.util_panel.axes_energy_Ef.valueChanged.connect(self.apply_energy_correction)
        self.util_panel.axes_energy_hv.valueChanged.connect(self.apply_energy_correction)
        self.util_panel.axes_energy_wf.valueChanged.connect(self.apply_energy_correction)
        self.util_panel.axes_energy_scale.currentIndexChanged.connect(self.apply_energy_correction)
        self.util_panel.axes_conv_lc.valueChanged.connect(self.update_main_plot)
        self.util_panel.axes_copy_values.clicked.connect(self.copy_values_orientate_to_axes)
        self.util_panel.axes_do_kspace_conv.clicked.connect(self.convert_to_kspace)
        self.util_panel.axes_reset_conv.clicked.connect(self.reset_kspace_conversion)

        # orientating options
        self.util_panel.orientate_init_x.valueChanged.connect(self.set_orientating_lines)
        self.util_panel.orientate_init_y.valueChanged.connect(self.set_orientating_lines)
        self.util_panel.orientate_find_gamma.clicked.connect(self.find_gamma)
        self.util_panel.orientate_copy_coords.clicked.connect(self.copy_values_volume_to_orientate)
        self.util_panel.orientate_hor_line.stateChanged.connect(self.set_orientating_lines)
        self.util_panel.orientate_ver_line.stateChanged.connect(self.set_orientating_lines)
        self.util_panel.orientate_angle.valueChanged.connect(self.set_orientating_lines)
        self.util_panel.orientate_info_button.clicked.connect(self.show_orientation_info)

        # Align all the gui elements
        self._align()
        self.show()

    def _align(self):
        """ Align all the GUI elements in the QLayout::

              0   1   2   3
            +---+---+---+---+
            |utilities panel| 0
            +---+---+---+---+
            | mdc x |       | 1
            +-------+  edc  |
            | cut x |       | 2
            +-------+-------+
            |       | c | m | 3
            | main  | y | y | 4
            +---+---+---+---+

            (Units of subdivision [sd])
        """
        # subdivision
        sd = 1
        # Get a short handle
        l = self.layout
        # addWidget(row, column, rowSpan, columnSpan)
        # utilities bar
        l.addWidget(self.util_panel,    0,      0,          2 * sd, 5 * sd)
        # X cut and mdc
        l.addWidget(self.plot_x,        2 * sd, 0,          1 * sd, 2 * sd)
        l.addWidget(self.cut_x,         3 * sd, 0,          1 * sd, 2 * sd)
        # Main plot
        l.addWidget(self.main_plot,     4 * sd, 0,          2 * sd, 2 * sd)
        # Y cut and mdc
        l.addWidget(self.cut_y,         4 * sd, 2,          2 * sd, 1 * sd)
        l.addWidget(self.plot_y,        4 * sd, 3 * sd,     2 * sd, 1 * sd)
        # EDC (integrated)
        l.addWidget(self.plot_z,        2 * sd, 2 * sd,     2 * sd, 2 * sd)

        nrows = 6 * sd
        ncols = 4 * sd
        # Need to manually set all row- and columnspans as well as min-sizes
        for i in range(nrows):
            l.setRowMinimumHeight(i, 50)
            # l.setRowMaximumHeight(i, 51)
            l.setRowStretch(i, 1)
        for i in range(ncols):
            l.setColumnMinimumWidth(i, 50)
            # l.setColumnMaximumWidth(i, 51)
            l.setColumnStretch(i, 1)

    def closeEvent(self, event):
        """ Ensure that this instance is un-registered from the DataBrowser. """
        del(self.db.data_viewers[self.index])

    def update_main_plot(self, **image_kwargs):
        """ Change *self.main_plot*`s currently displayed
        :class:`image_item <data_slicer.imageplot.ImagePlot.image_item>` to
        the slice of *self.data_handler.data* corresponding to the current
        value of *self.z*.
        """
        slider_pos = self.get_sliders_positions()
        self.data_handler.update_image_data()

        if image_kwargs != {}:
            self.image_kwargs = image_kwargs

        # Add image to main_plot
        self.set_image(self.image_data, **image_kwargs)
        self.set_sliders_postions(slider_pos)
        self.update_xy_binning_lines()
        self.show_BZ_contour()

    def set_axes(self):
        """ Set the x- and y-scales of the plots. The :class:`ImagePlot
        <data_slicer.imageplot.ImagePlot>` object takes care of keeping the
        scales as they are, once they are set.
        """
        xaxis = self.data_handler.axes[scan_ax]
        yaxis = self.data_handler.axes[slit_ax]
        zaxis = self.data_handler.axes[erg_ax]
        # self.main_plot.set_xscale(xaxis)
        self.main_plot.set_xscale(range(0, len(xaxis)))
        self.main_plot.set_ticks(xaxis[0], xaxis[-1], self.main_plot.main_xaxis)
        self.cut_x.set_ticks(xaxis[0], xaxis[-1], self.cut_x.main_xaxis)
        self.cut_y.set_ticks(yaxis[0], yaxis[-1], self.cut_y.main_xaxis)
        self.plot_x.set_ticks(xaxis[0], xaxis[-1], self.plot_x.main_xaxis)
        self.plot_x.set_secondary_axis(0, len(xaxis))
        # self.main_plot.set_yscale(yaxis)
        self.main_plot.set_yscale(range(0, len(yaxis)))
        self.main_plot.set_ticks(yaxis[0], yaxis[-1], self.main_plot.main_yaxis)
        self.cut_x.set_ticks(zaxis[0], zaxis[-1], self.cut_x.main_yaxis)
        self.cut_y.set_ticks(zaxis[0], zaxis[-1], self.cut_y.main_yaxis)
        self.plot_y.set_ticks(yaxis[0], yaxis[-1], self.plot_y.main_xaxis)
        self.plot_y.set_secondary_axis(0, len(yaxis))
        self.main_plot.fix_viewrange()

    def update_plot_x(self):
        # Get shorthands for plot
        xp = self.plot_x
        try:
            old = xp.listDataItems()[0]
            xp.removeItem(old)
        except IndexError:
            pass

        # Get the correct position indicator
        pos = self.cut_x.crosshair.hpos
        if pos.allowed_values is not None:
            i_x = int(min(pos.get_value(), pos.allowed_values.max() - 1))
        else:
            i_x = 0
        if self.util_panel.bin_zx.isChecked():
            bins = self.util_panel.bin_zx_nbins.value()
            start, stop = i_x - bins, i_x + bins
            with warnings.catch_warnings():
                y = wp.normalize(np.sum(self.data_handler.cut_x_data[:, start:stop], axis=1))
        else:
            y = self.data_handler.cut_x_data[:, i_x]
        x = np.arange(0, len(self.data_handler.axes[scan_ax]))
        self.plot_x_data = y
        xp.plot(x, y)
        self.util_panel.energy_hor.setValue(i_x)
        if self.new_energy_axis is None:
            self.util_panel.energy_hor_value.setText('({:.4f})'.format(self.data_handler.axes[erg_ax][i_x]))
        else:
            self.util_panel.energy_hor_value.setText('({:.4f})'.format(self.new_energy_axis[i_x]))
        self.update_zx_zy_binning_line()

    def update_plot_y(self):
        # Get shorthands for plot
        yp = self.plot_y
        try:
            old = yp.listDataItems()[0]
            yp.removeItem(old)
        except IndexError:
            pass

        # Get the correct position indicator
        pos = self.cut_y.crosshair.hpos
        if pos.allowed_values is not None:
            i_x = int(min(pos.get_value(), pos.allowed_values.max() - 1))
        else:
            i_x = 0
        if self.util_panel.bin_zy.isChecked():
            bins = self.util_panel.bin_zy_nbins.value()
            start, stop = i_x - bins, i_x + bins
            with warnings.catch_warnings():
                y = wp.normalize(np.sum(self.data_handler.cut_y_data[start:stop, :], axis=0))
        else:
            y = self.data_handler.cut_y_data[i_x, :]
        x = np.arange(0, len(self.data_handler.axes[slit_ax]))
        self.plot_y_data = y
        yp.plot(y, x)
        self.util_panel.energy_vert.setValue(i_x)
        if self.new_energy_axis is None:
            self.util_panel.energy_vert_value.setText('({:.4f})'.format(self.data_handler.axes[erg_ax][i_x]))
        else:
            self.util_panel.energy_vert_value.setText('({:.4f})'.format(self.new_energy_axis[i_x]))
        self.update_zx_zy_binning_line()

    def update_cut_x(self):
        """ Take a cut of *self.data_handler.data* along *self.cutline*. This
        is used to update only the cut plot without affecting the main plot.
        """
        data = self.data_handler.get_data()
        # axes = self.data_handler.displayed_axes
        # Transpose, if necessary
        pos = self.main_plot.crosshair.hpos
        if pos.allowed_values is not None:
            i_x = int(min(pos.get_value(), pos.allowed_values.max() - 1))
        else:
            i_x = 0
        try:
            if self.util_panel.bin_y.isChecked():
                bins = self.util_panel.bin_y_nbins.value()
                start, stop = i_x - bins, i_x + bins
                cut = np.sum(data[:, start:stop, :], axis=1)
            else:
                cut = data[:, i_x, :]
        except IndexError:
            return

        if self.util_panel.bin_x.isChecked():
            binning = self.util_panel.bin_x_nbins.value()
        else:
            binning = 0

        self.data_handler.cut_x_data = cut
        self.cut_x.xscale_rescaled = self.data_handler.axes[scan_ax]
        self.cut_x.yscale_rescaled = self.data_handler.axes[erg_ax]
        self.set_cut_x_image(image=cut, lut=self.lut)
        self.cut_x.crosshair.vpos.set_allowed_values(np.arange(0, len(self.data_handler.axes[scan_ax])),
                                                     binning=binning)
        self.cut_x.crosshair.hpos.set_allowed_values(np.arange(0, len(self.data_handler.axes[erg_ax])),
                                                     binning=binning)
        self.cut_x.set_bounds(0, len(self.data_handler.axes[scan_ax]), 0, len(self.data_handler.axes[erg_ax]))

        self.cut_x.fix_viewrange()

        # update values of momentum at utilities panel
        self.util_panel.momentum_hor.setValue(i_x)
        if self.ky_axis is None:
            self.util_panel.momentum_hor_value.setText('({:.3f})'.format(self.data_handler.axes[slit_ax][i_x]))
        else:
            self.util_panel.momentum_hor_value.setText('({:.3f})'.format(self.ky_axis[i_x]))


        # update EDC at crossing point
        if self.sp_EDC is not None:
            self.set_sp_EDC_data()

        self.update_xy_binning_lines()

    def update_cut_y(self):
        """ Take a cut of *self.data_handler.data* along *self.cutline*. This
        is used to update only the cut plot without affecting the main plot.
        """
        data = self.data_handler.get_data()
        # axes = self.data_handler.displayed_axes
        # Transpose, if necessary
        pos = self.cut_x.crosshair.vpos
        if pos.allowed_values is not None:
            i_x = int(min(pos.get_value(), pos.allowed_values.max() - 1))
        else:
            i_x = 0
        try:
            if self.util_panel.bin_x.isChecked():
                bins = self.util_panel.bin_x_nbins.value()
                start, stop = i_x - bins, i_x + bins
                cut = np.sum(data[start:stop, :, :], axis=0).T
            else:
                cut = data[i_x, :, :].T
        except IndexError:
            return

        self.data_handler.cut_y_data = cut
        self.cut_y.xscale_rescaled = self.data_handler.axes[slit_ax]
        self.cut_y.yscale_rescaled = self.data_handler.axes[erg_ax]
        self.set_cut_y_image(image=cut, lut=self.lut)
        # bounds swapped to match transposed dimensions
        self.cut_y.set_bounds(0, len(self.data_handler.axes[erg_ax]), 0, len(self.data_handler.axes[slit_ax]))

        self.cut_y.fix_viewrange()

        # update values of momentum at utilities panel
        self.util_panel.momentum_vert.setValue(i_x)
        if self.kx_axis is None:
            self.util_panel.momentum_vert_value.setText('({:.3f})'.format(self.data_handler.axes[scan_ax][i_x]))
        else:
            self.util_panel.momentum_vert_value.setText('({:.3f})'.format(self.kx_axis[i_x]))
        self.update_xy_binning_lines()

        # update EDC at crossing point
        if self.sp_EDC is not None:
            self.set_sp_EDC_data()

    def set_sp_EDC_data(self):
        try:
            xpos = self.main_plot.crosshair.vpos.get_value()
            ypos = self.main_plot.crosshair.hpos.get_value()
            bin_x, bin_y = self.util_panel.bin_x.isChecked(), self.util_panel.bin_y.isChecked()
            if bin_x and bin_y:
                nbx = self.util_panel.bin_x_nbins.value()
                nby = self.util_panel.bin_y_nbins.value()
                data = self.data_handler.get_data()[(xpos - nbx):(xpos + nbx), (ypos - nby):(ypos + nby), :]
                data = np.sum(np.sum(data, axis=1), axis=0)
            elif bin_x:
                nbx = self.util_panel.bin_x_nbins.value()
                data = self.data_handler.get_data()[(xpos - nbx):(xpos + nbx), ypos, :]
                data = np.sum(data, axis=0)
            elif bin_y:
                nby = self.util_panel.bin_y_nbins.value()
                data = self.data_handler.get_data()[xpos, (ypos - nby):(ypos + nby), :]
                data = np.sum(data, axis=0)
            else:
                data = self.data_handler.get_data()[xpos, ypos, :]
            with warnings.catch_warnings():
                data = wp.normalize(data)
            self.sp_EDC.setData(data, pen=self.plot_z.sp_EDC_pen)
        except Exception:
            pass

    def redraw_plots(self, image=None):
        """ Redraw plotted data to reflect changes in data or its colors. """
        try:
            # Redraw main plot
            self.set_image(image, displayed_axes=self.data_handler.displayed_axes)
            # Redraw cut plot
            self.update_cut()
        except AttributeError:
            pass

    def set_image(self, image=None, *args, **kwargs):
        """ Wraps the underlying ImagePlot3d's set_image method.
        See :func:`~data_slicer.imageplot.ImagePlot3d.set_image`. *image* can
        be *None* i.e. in order to just update the plot with a new colormap.
        """

        # Reset the transformation
        self._transform_factors = []
        # pmesh = self.util_panel.image_pmesh.isChecked()
        # try:
        #     pmesh_x, pmesh_y = self.pmesh_kx_axis, self.pmesh_ky_axis
        # except AttributeError:
        #     pmesh_x, pmesh_y = None, None
        if image is None:
            image = self.image_data
        # self.main_plot.set_image(image, pmesh=pmesh, pmesh_x=pmesh_x, pmesh_y=pmesh_y,
        #                          *args, lut=self.lut, **kwargs)
        self.main_plot.set_image(image, *args, lut=self.lut, **kwargs)
        self.set_orientating_lines()

    def set_cut_x_image(self, image=None, *args, **kwargs):
        """ Wraps the underlying ImagePlot3d's set_image method.
        See :func:`~data_slicer.imageplot.ImagePlot3d.set_image`. *image* can
        be *None* i.e. in order to just update the plot with a new colormap.
        """

        # Reset the transformation
        self._transform_factors = []
        if image is None:
            image = self.image_data
        self.cut_x.set_image(image, *args, **kwargs)

    def set_cut_y_image(self, image=None, *args, **kwargs):
        """ Wraps the underlying ImagePlot3d's set_image method.
        See :func:`~data_slicer.imageplot.ImagePlot3d.set_image`. *image* can
        be *None* i.e. in order to just update the plot with a new colormap.
        """

        # Reset the transformation
        self._transform_factors = []
        if image is None:
            image = self.image_data
        self.cut_y.set_image(image, *args, **kwargs)

    # color methods
    def set_cmap(self):
        """ Set the colormap to *cmap* where *cmap* is one of the names
        registered in :mod:`<data_slicer.cmaps>` which includes all matplotlib and
        kustom cmaps.
        WP: small changes made to use only my list of cmaps (see cmaps.py) and to shorten the list
        by using 'invert_colors' checkBox
        """
        try:
            cmap = self.util_panel.image_cmaps.currentText()
            if self.util_panel.image_invert_colors.isChecked() and ip.MY_CMAPS:
                cmap = cmap + '_r'
        except AttributeError:
            cmap = p2d.DEFAULT_CMAP

        try:
            self.cmap = cmaps[cmap]
        except KeyError:
            print('Invalid colormap name. Use one of: ')
            print(cmaps.keys())
        self.cmap_name = cmap
        # Since the cmap changed it forgot our settings for alpha and gamma
        self.cmap.set_alpha(self.alpha)
        self.cmap.set_gamma()
        sliders_pos = self.get_sliders_positions()
        self.cmap_changed()
        self.set_sliders_postions(sliders_pos)
        self.update_z_binning_lines()

    def cmap_changed(self):
        """ Recalculate the lookup table and redraw the plots such that the
        changes are immediately reflected.
        """
        self.lut = self.cmap.getLookupTable()
        self.redraw_plots()

    def set_alpha(self, alpha):
        """ Set the alpha value of the currently used cmap. *alpha* can be a
        single float or an array of length ``len(self.cmap.color)``.
        """
        self.alpha = alpha
        sliders_pos = self.get_sliders_positions()
        self.cmap.set_alpha(alpha)
        self.cmap_changed()
        self.set_sliders_postions(sliders_pos)
        self.update_z_binning_lines()
        self.set_x_binning_lines()
        self.set_y_binning_lines()

    def set_gamma(self):
        """ Set the exponent for the power-law norm that maps the colors to
        values. I.e. the values where the colours are defined are mapped like
        ``y=x**gamma``.
        WP: changed to work with applied QDoubleSpinBox
        """
        gamma = self.util_panel.image_gamma.value()
        self.gamma = gamma
        sliders_pos = self.get_sliders_positions()
        self.cmap.set_gamma(gamma)
        self.cmap_changed()
        self.update_z_binning_lines()
        self.set_sliders_postions(sliders_pos)
        self.set_x_binning_lines()
        self.set_y_binning_lines()

    def set_colorscale(self):
        """ Set the relative maximum of the colormap. I.e. the colors are
        mapped to the range `min(data)` - `vmax*max(data)`.
        WP: changed to work with applied QDoubleSpinBox
        """
        vmax = self.util_panel.image_colorscale.value()
        self.vmax = vmax
        sliders_pos = self.get_sliders_positions()
        self.cmap.set_vmax(vmax)
        self.cmap_changed()
        self.set_sliders_postions(sliders_pos)
        self.set_x_binning_lines()
        self.set_y_binning_lines()

    # sliders and binning methods
    def set_x_binning_lines(self):
        """ Update binning lines accordingly. """
        # horizontal cut
        if self.util_panel.bin_x.isChecked():
            try:
                half_width = self.util_panel.bin_x_nbins.value()
                pos = self.main_plot.pos[0].get_value()
                self.main_plot.add_binning_lines(pos, half_width, orientation='vertical')
                self.cut_x.add_binning_lines(pos, half_width, orientation='vertical')
                self.plot_x.add_binning_lines(pos, half_width)
                xmin = half_width
                xmax = len(self.data_handler.axes[0]) - half_width
                new_range = np.arange(xmin, xmax)
                self.main_plot.pos[0].set_allowed_values(new_range)
                self.cut_x.pos[0].set_allowed_values(new_range)
                self.plot_x.pos.set_allowed_values(new_range)
            except AttributeError:
                pass
        else:
            try:
                self.main_plot.remove_binning_lines(orientation='vertical')
                self.cut_x.remove_binning_lines(orientation='vertical')
                self.plot_x.remove_binning_lines()
                org_range = np.arange(0, len(self.data_handler.axes[0]))
                self.main_plot.pos[0].set_allowed_values(org_range)
                self.cut_x.pos[0].set_allowed_values(org_range)
                self.plot_x.pos.set_allowed_values(org_range)
            except AttributeError:
                pass

    def set_y_binning_lines(self):
        """ Update binning lines accordingly. """
        # vertical cut
        if self.util_panel.bin_y.isChecked():
            try:
                half_width = self.util_panel.bin_y_nbins.value()
                pos = self.main_plot.pos[1].get_value()
                self.main_plot.add_binning_lines(pos, half_width)
                self.cut_y.add_binning_lines(pos, half_width)
                self.plot_y.add_binning_lines(pos, half_width)
                ymin = half_width
                ymax = len(self.data_handler.axes[1]) - half_width
                new_range = np.arange(ymin, ymax)
                self.main_plot.pos[1].set_allowed_values(new_range)
                self.cut_y.pos[0].set_allowed_values(new_range)
                self.plot_y.pos.set_allowed_values(new_range)
            except AttributeError:
                pass
        else:
            try:
                self.main_plot.remove_binning_lines()
                self.cut_y.remove_binning_lines()
                self.plot_y.remove_binning_lines()
                org_range = np.arange(0, len(self.data_handler.axes[1]))
                self.main_plot.pos[1].set_allowed_values(org_range)
                self.cut_y.pos[0].set_allowed_values(org_range)
                self.plot_y.pos.set_allowed_values(org_range)
            except AttributeError:
                pass

    def set_zx_binning_line(self):
        # horizontal plot
        if self.util_panel.bin_zx.isChecked():
            try:
                half_width = self.util_panel.bin_zx_nbins.value()
                pos = self.cut_x.pos[1].get_value()
                self.cut_x.add_binning_lines(pos, half_width)
                zmin = half_width
                zmax = len(self.data_handler.axes[erg_ax]) - half_width
                new_range = np.arange(zmin, zmax)
                self.cut_x.pos[1].set_allowed_values(new_range)
            except AttributeError:
                pass
        else:
            try:
                self.cut_x.remove_binning_lines()
                org_range = np.arange(0, len(self.data_handler.axes[erg_ax]))
                self.cut_x.pos[1].set_allowed_values(org_range)
            except AttributeError:
                pass

    def set_zy_binning_line(self):
        # vertical plot
        if self.util_panel.bin_zy.isChecked():
            try:
                half_width = self.util_panel.bin_zy_nbins.value()
                pos = self.cut_y.pos[1].get_value()
                self.cut_y.add_binning_lines(pos, half_width, orientation='vertical')
                zmin = half_width
                zmax = len(self.data_handler.axes[erg_ax]) - half_width
                new_range = np.arange(zmin, zmax)
                self.cut_y.pos[1].set_allowed_values(new_range)
            except AttributeError:
                pass
        else:
            try:
                self.cut_y.remove_binning_lines(orientation='vertical')
                org_range = np.arange(0, len(self.data_handler.axes[erg_ax]))
                self.cut_y.pos[1].set_allowed_values(org_range)
            except AttributeError:
                pass

    def update_xy_binning_lines(self):
        if self.util_panel.bin_x.isChecked():
            try:
                pos = self.main_plot.pos[0].get_value()
                half_width = self.util_panel.bin_x_nbins.value()
                self.main_plot.add_binning_lines(pos, half_width, orientation='vertical')
                self.cut_x.add_binning_lines(pos, half_width, orientation='vertical')
                self.plot_x.add_binning_lines(pos, half_width)
            except AttributeError:
                pass
        else:
            pass

        if self.util_panel.bin_y.isChecked():
            try:
                pos = self.main_plot.pos[1].get_value()
                half_width = self.util_panel.bin_y_nbins.value()
                self.main_plot.add_binning_lines(pos, half_width)
                self.cut_y.add_binning_lines(pos, half_width)
                self.plot_y.add_binning_lines(pos, half_width)
            except AttributeError:
                pass
        else:
            pass

    def update_zx_zy_binning_line(self):
        if self.util_panel.bin_zx.isChecked():
            try:
                pos = self.cut_x.pos[1].get_value()
                half_width = self.util_panel.bin_zx_nbins.value()
                self.cut_x.add_binning_lines(pos, half_width)
            except AttributeError:
                pass
        else:
            pass

        if self.util_panel.bin_zy.isChecked():
            try:
                pos = self.cut_y.pos[1].get_value()
                half_width = self.util_panel.bin_zy_nbins.value()
                self.cut_y.add_binning_lines(pos, half_width, orientation='vertical')
            except AttributeError:
                pass
        else:
            pass

    def update_z_binning_lines(self):
        """ Update binning lines accordingly. """
        if self.util_panel.bin_z.isChecked():
            try:
                half_width = self.util_panel.bin_z_nbins.value()
                z_pos = self.data_handler.z.get_value()
                self.plot_z.add_binning_lines(z_pos, half_width)
                zmin = half_width
                zmax = len(self.data_handler.axes[2]) - half_width
                new_range = np.arange(zmin, zmax)
                self.plot_z.width = half_width
                self.plot_z.n_bins = half_width
                self.plot_z.pos.set_allowed_values(new_range)
                # self.update_main_plot(emit=False)
            except AttributeError:
                pass
        else:
            try:
                self.plot_z.remove_binning_lines()
                self.data_handler.update_z_range()
            except AttributeError:
                pass

    def set_main_energy_slider(self):
        energy = self.util_panel.energy_main.value()
        self.data_handler.z.set_value(energy)

    def set_hor_energy_slider(self):
        energy = self.util_panel.energy_hor.value()
        self.cut_x.crosshair.hpos.set_value(energy)

    def set_vert_energy_slider(self):
        energy = self.util_panel.energy_vert.value()
        self.cut_y.crosshair.hpos.set_value(energy)

    def set_hor_momentum_slider(self):
        angle = self.util_panel.momentum_hor.value()
        self.main_plot.pos[1].set_value(angle)

    def set_vert_momentum_slider(self):
        angle = self.util_panel.momentum_vert.value()
        self.main_plot.pos[0].set_value(angle)

    def put_sliders_in_initial_positions(self):
        if self.new_energy_axis is None:
            e_ax = self.data_handler.axes[erg_ax]
        else:
            e_ax = self.new_energy_axis
        if (e_ax.min() < 0) and (e_ax.max() > 0):
            mid_energy = wp.indexof(-0.005, e_ax)
        else:
            mid_energy = int(len(e_ax) / 2)
            self.util_panel.axes_energy_scale.setCurrentIndex(1)

        if self.kx_axis is None:
            mh_ax = self.data_handler.axes[scan_ax]
        else:
            mh_ax = self.kx_axis
        if (mh_ax.min() < 0) and (mh_ax.max() > 0):
            mid_hor_angle = wp.indexof(0, mh_ax)
        else:
            mid_hor_angle = int(len(mh_ax) / 2)

        if self.ky_axis is None:
            mv_ax = self.data_handler.axes[slit_ax]
        else:
            mv_ax = self.ky_axis
        if (mv_ax.min() < 0) and (mv_ax.max() > 0):
            mid_vert_angle = wp.indexof(0, mv_ax)
        else:
            mid_vert_angle = int(len(mv_ax) / 2)

        self.data_handler.z.set_value(mid_energy)
        self.cut_x.crosshair.hpos.set_value(mid_energy)
        self.cut_y.crosshair.hpos.set_value(mid_energy)
        self.main_plot.pos[0].set_value(mid_hor_angle)
        self.main_plot.pos[1].set_value(mid_vert_angle)

    def set_pmesh_axes(self):
        if self.kx_axis is None:
            mh_ax = self.data_handler.axes[scan_ax]
        else:
            mh_ax = self.kx_axis

        if self.ky_axis is None:
            mv_ax = self.data_handler.axes[slit_ax]
        else:
            mv_ax = self.ky_axis

        tmp_mh_ax = np.arange(mh_ax.size + 1)
        # tmp_mh_ax[:-1] = mh_ax
        # tmp_mh_ax[-1] = mh_ax[-1] + wp.get_step(mh_ax)

        tmp_mv_ax = np.arange(mv_ax.size + 1)
        # tmp_mv_ax[:-1] = mv_ax
        # tmp_mv_ax[-1] = mv_ax[-1] + wp.get_step(mv_ax)

        self.pmesh_kx_axis, self.pmesh_ky_axis = np.meshgrid(tmp_mh_ax, tmp_mv_ax)
        self.pmesh_kx_axis, self.pmesh_ky_axis = self.pmesh_kx_axis.T, self.pmesh_ky_axis.T
        # print(mh_ax.shape, mv_ax.shape, self.pmesh_kx_axis.shape, self.pmesh_ky_axis.shape)

    def get_sliders_positions(self):
        main_hor = self.main_plot.crosshair.hpos.get_value()
        main_ver = self.main_plot.crosshair.vpos.get_value()
        cut_hor_energy = self.cut_x.crosshair.hpos.get_value()
        cut_ver_energy = self.cut_y.crosshair.hpos.get_value()
        return [main_hor, main_ver, cut_hor_energy, cut_ver_energy]

    def set_sliders_postions(self, positions):
        self.main_plot.pos[1].set_value(positions[0])
        self.main_plot.pos[0].set_value(positions[1])
        self.cut_x.pos[1].set_value(positions[2])
        self.cut_y.pos[1].set_value(positions[3])

    def set_sliders_labels(self, dataset):
        if hasattr(dataset, 'scan_type'):
            if dataset.scan_type == 'hv scan':
                self.util_panel.momentum_vert_label.setText('hv:')
                self.util_panel.energy_hor_label.setText('hv:')
                self.util_panel.bin_x.setText('bin hv')
                self.util_panel.bin_zx.setText('bin E (hv)')
        else:
            return

    def apply_energy_correction(self):
        Ef = self.util_panel.axes_energy_Ef.value()
        hv = self.util_panel.axes_energy_hv.value()
        wf = self.util_panel.axes_energy_wf.value()

        scale = self.util_panel.axes_energy_scale.currentText()
        if scale == 'binding':
            hv = 0
            wf = 0

        new_energy_axis = self.data_handler.axes[erg_ax] + Ef - hv + wf
        self.new_energy_axis = new_energy_axis
        new_range = [new_energy_axis[0], new_energy_axis[-1]]
        self.cut_x.plotItem.getAxis(self.cut_x.main_yaxis).setRange(*new_range)
        self.cut_y.plotItem.getAxis(self.cut_y.main_yaxis).setRange(*new_range)
        self.plot_z.plotItem.getAxis(self.plot_z.main_xaxis).setRange(*new_range)

        # update energy labels
        main_erg_idx = self.plot_z.pos.get_value()
        cut_x_erg_idx = self.cut_x.crosshair.hpos.get_value()
        cut_y_erg_idx = self.cut_y.crosshair.hpos.get_value()
        self.util_panel.energy_main_value.setText('({:.4f})'.format(self.new_energy_axis[main_erg_idx]))
        self.util_panel.energy_hor_value.setText('({:.4f})'.format(self.new_energy_axis[cut_x_erg_idx]))
        self.util_panel.energy_vert_value.setText('({:.4f})'.format(self.new_energy_axis[cut_y_erg_idx]))

    # analysis options
    def find_gamma(self):
        fs = self.image_data.T
        x_init = self.util_panel.orientate_init_x.value()
        y_init = self.util_panel.orientate_init_y.value()
        res = wp.find_gamma(fs, x_init, y_init)
        if res.success:
            self.util_panel.orientate_find_gamma_message.setText('Success,  values found!')
            self.util_panel.orientate_init_x.setValue(int(res.x[0]))
            self.util_panel.orientate_init_y.setValue(int(res.x[1]))
        else:
            self.util_panel.orientate_find_gamma_message.setText('Couldn\'t find center of rotation.')

    def copy_values_volume_to_orientate(self):
        self.util_panel.orientate_init_x.setValue(self.util_panel.momentum_vert.value())
        self.util_panel.orientate_init_y.setValue(self.util_panel.momentum_hor.value())

    def copy_values_orientate_to_axes(self):
        self.util_panel.axes_gamma_x.setValue(self.util_panel.orientate_init_x.value())
        self.util_panel.axes_gamma_y.setValue(self.util_panel.orientate_init_y.value())

    def set_orientating_lines(self):

        x0 = self.util_panel.orientate_init_x.value()
        y0 = self.util_panel.orientate_init_y.value()

        try:
            self.main_plot.removeItem(self.orient_hor_line)
        except AttributeError:
            pass
        if self.util_panel.orientate_hor_line.isChecked():
            angle = self.transform_angle(self.util_panel.orientate_angle.value())
            if (-180 < angle < 90) and (angle != -90):
                beta = np.deg2rad(angle)
                if angle == 0:
                    y_pos = y0
                else:
                    y_pos = y0 + (x0 * np.tan(beta))
                angle = -angle
            elif (angle == 90) or (angle == -90):
                self.orient_hor_line = InfiniteLine(x0, movable=False)
                self.orient_hor_line.setPen(color=ORIENTLINES_LINECOLOR, width=3)
                self.main_plot.addItem(self.orient_hor_line)
                return
            elif 90 < angle < 180:
                beta = np.pi - np.deg2rad(angle)
                y_pos = y0 - (x0 * np.tan(beta))
                angle = -angle
            elif (angle == -180) or (angle == 180):
                y_pos = y0
                angle = 0
            self.orient_hor_line = InfiniteLine(y_pos, movable=False, angle=0)
            self.orient_hor_line.setPen(color=ORIENTLINES_LINECOLOR, width=3)
            self.orient_hor_line.setAngle(angle)
            self.main_plot.addItem(self.orient_hor_line)

        try:
            self.main_plot.removeItem(self.orient_ver_line)
        except AttributeError:
            pass
        if self.util_panel.orientate_ver_line.isChecked():
            angle = self.transform_angle(self.util_panel.orientate_angle.value(), orientation='vertical')
            if (-180 < angle < 90) and (angle != -90) and (angle != 90):
                beta = 0.5 * np.pi - np.deg2rad(angle)
                x_pos = x0 - (y0 / np.tan(beta))
                angle = 90 - angle
            elif (angle == 90) or (angle == -90):
                self.orient_ver_line = InfiniteLine(y0, movable=False, angle=0)
                self.orient_ver_line.setPen(color=ORIENTLINES_LINECOLOR, width=3)
                self.main_plot.addItem(self.orient_ver_line)
                return
            elif 90 < angle < 180:
                beta = np.deg2rad(angle) - 0.5 * np.pi
                x_pos = x0 + (y0 / np.tan(beta))
                angle = 90 - angle
            elif (angle == -180) or (angle == 180):
                x_pos = x0
                angle = 90
            self.orient_ver_line = InfiniteLine(x_pos, movable=False)
            self.orient_ver_line.setPen(color=ORIENTLINES_LINECOLOR, width=3)
            self.orient_ver_line.setAngle(angle)
            self.main_plot.addItem(self.orient_ver_line)

    def transform_angle(self, angle, orientation='horizontal'):
        coeff = wp.get_step(self.data_handler.axes[scan_ax]) / wp.get_step(self.data_handler.axes[slit_ax])
        if orientation == 'horizontal':
            return np.rad2deg(np.arctan(np.tan(np.deg2rad(angle)) * coeff))
        else:
            return np.rad2deg(np.arctan(np.tan(np.deg2rad(angle)) / coeff))

    def convert_to_kspace(self):
        scanned_ax = self.data_handler.axes[scan_ax]
        anal_axis = self.data_handler.axes[slit_ax]
        d_anal_ax = self.data_handler.axes[slit_ax][
            self.util_panel.axes_gamma_y.value()]
        d_scan_ax = self.data_handler.axes[scan_ax][
            self.util_panel.axes_gamma_x.value()]
        orientation = self.util_panel.axes_slit_orient.currentText()
        a = self.util_panel.axes_conv_lc.value()
        # try:
        #     energy = self.new_energy_axis[self.data_handler.z.get_value()]
        # except TypeError:
        #     energy = self.data_handler.axes[erg_ax][self.data_handler.z.get_value()]
        hv = self.util_panel.axes_energy_hv.value()
        wf = self.util_panel.axes_energy_wf.value()
        ds = self.data_set
        new_dataset = deepcopy(ds)

        info_box = QMessageBox()
        info_box.setIcon(QMessageBox.Information)
        info_box.setWindowTitle('K-space conversion.')
        msg = 'Conversion might take a while,  ' \
              'depending on the dataset\'s size.\n' \
              'Make sure all parameters are correct and be patient.'.format()
        info_box.setText(msg)
        info_box.setStandardButtons(QMessageBox.Cancel | QMessageBox.Ok)
        choice = info_box.exec()
        if choice == QMessageBox.Ok:
            pass
        elif choice == QMessageBox.Cancel:
            return

        if self.util_panel.axes_transform_kz.isChecked():
            ky, _ = wp.hv2kz(anal_axis, scanned_ax, d_scan_ax=d_scan_ax, d_anal_ax=d_anal_ax, a=a,
                             orientation = orientation)
            y_min, y_max, min_step = ky[-1].min(), ky[-1].max(), wp.get_step(ky[0])
            new_yscale = np.arange(y_min, y_max, min_step)

            print('rescaling data: ', end='')
            start_time = time.time()
            dataset_rescaled = wp.rescale_data(ds.data, ky, new_yscale)  # , ProgressBar(total=ds.zscale.size))
            # dataset_rescaled = wp.rescale_data(ds.data, ds.yscale, new_yscale, ProgressBar(total=ds.zscale.size))
            print('{:.4} s'.format(time.time() - start_time))
        else:
            if hv == 0 or wf == 0:
                warning_box = QMessageBox()
                warning_box.setIcon(QMessageBox.Information)
                warning_box.setWindowTitle('Wrong conversion values.')
                if hv == 0 and wf == 0:
                    msg = 'Photon energy and work function values not given.'
                elif hv == 0:
                    msg = 'Photon energy value not given.'
                elif wf == 0:
                    msg = 'Work function value not given.'
                warning_box.setText(msg)
                warning_box.setStandardButtons(QMessageBox.Ok)
                if warning_box.exec() == QMessageBox.Ok:
                    return
            kx, ky = wp.angle2kspace(scanned_ax, anal_axis, d_scan_ax=d_scan_ax, d_anal_ax=d_anal_ax, a=a,
                                     orientation=orientation, hv=hv, work_func=wf)
            kxx, kyy = np.meshgrid(kx[:, 0], ky[0, :])
            cut = self.main_plot.image_data
            plt.pcolormesh(kxx, kyy, cut.T)
            y_min, y_max, min_step = ky.min(), ky.max(), wp.get_step(ky[0, :])
            new_yscale = np.arange(y_min, y_max, min_step)

            print('rescaling data: ', end='')
            start_time = time.time()
            dataset_rescaled = wp.rescale_data(ds.data, ky, new_yscale)  # , ProgressBar(total=ds.zscale.size))
            # dataset_rescaled = wp.rescale_data(ds.data, ds.yscale, new_yscale, ProgressBar(total=ds.zscale.size))
            print('{:.4} s'.format(time.time() - start_time))
            new_dataset.xscale = kx[:, 0]
            new_dataset.kxscale = kx[:, 0]
        new_dataset.data = dataset_rescaled
        new_dataset.yscale = new_yscale
        new_dataset.kyscale = new_yscale
        new_idx = self.index + ' [rescaled to k-space]'

        try:
            self.db.data_viewers[new_idx] = MainWindow3D(self.db, data_set=new_dataset, index=new_idx)
        except Exception:
            fail_box = QMessageBox()
            fail_box.setIcon(QMessageBox.Information)
            fail_box.setWindowTitle('K-space conversion.')
            msg = 'Something went wrong.<br>' \
                  'K-space conversion failed.'
            fail_box.setText(msg)
            fail_box.setStandardButtons(QMessageBox.Ok)
            if fail_box.exec() == QMessageBox.Ok:
                return

        success_box = QMessageBox()
        success_box.setIcon(QMessageBox.Information)
        success_box.setWindowTitle('Conversion succeed.')
        msg = 'K-space conversion succeed!<br>' \
              'Make sure to save results.'
        success_box.setText(msg)
        success_box.setStandardButtons(QMessageBox.Ok)
        if success_box.exec() == QMessageBox.Ok:
            return

        # kx_axis, ky_axis = wp.angle2kscape(scanned_ax, anal_axis, d_scan_ax=d_scan_ax, d_anal_ax=d_anal_ax,
        #                                    orientation=orientation, a=a, energy=energy, hv=hv, work_func=wf)
        # nhma = np.sort(kx_axis[:, 0])
        # nvma = np.sort(ky_axis[0, :])
        # self.kx_axis = nhma
        # self.ky_axis = nvma
        # self.pmesh_kx_axis, self.pmesh_ky_axis = kx_axis, ky_axis
        # new_hor_range = [nhma[0], nhma[-1]]
        # new_ver_range = [nvma[0], nvma[-1]]
        # # print(kx_axis.min(), kx_axis.max(), ky_axis.min(), ky_axis.max())
        # # print(nhma.size, nvma.size)
        # # print([nhma[0], nhma[-1]])
        # # print([nvma[0], nvma[-1]])
        # self.main_plot.plotItem.getAxis(self.main_plot.main_xaxis).setRange(*new_hor_range)
        # self.main_plot.plotItem.getAxis(self.main_plot.main_yaxis).setRange(*new_ver_range)
        # self.cut_x.plotItem.getAxis(self.cut_x.main_xaxis).setRange(*new_hor_range)
        # self.cut_y.plotItem.getAxis(self.cut_y.main_xaxis).setRange(*new_ver_range)
        # self.plot_x.plotItem.getAxis(self.plot_x.main_xaxis).setRange(*new_hor_range)
        # self.plot_y.plotItem.getAxis(self.plot_y.main_xaxis).setRange(*new_ver_range)
        # self.util_panel.momentum_hor_value.setText('({:.4f})'.format(
        #     self.ky_axis[self.main_plot.pos[1].get_value()]))
        # self.util_panel.momentum_vert_value.setText('({:.4f})'.format(
        #     self.kx_axis[self.main_plot.pos[0].get_value()]))

    def reset_kspace_conversion(self):
        self.kx_axis = None
        self.ky_axis = None
        org_hor_range = [self.data_handler.axes[0][0], self.data_handler.axes[0][-1]]
        org_ver_range = [self.data_handler.axes[1][0], self.data_handler.axes[1][-1]]
        self.main_plot.plotItem.getAxis(self.main_plot.main_xaxis).setRange(*org_hor_range)
        self.main_plot.plotItem.getAxis(self.main_plot.main_yaxis).setRange(*org_ver_range)
        self.cut_x.plotItem.getAxis(self.cut_x.main_xaxis).setRange(*org_hor_range)
        self.cut_y.plotItem.getAxis(self.cut_y.main_xaxis).setRange(*org_ver_range)
        self.plot_x.plotItem.getAxis(self.plot_x.main_xaxis).setRange(*org_hor_range)
        self.plot_y.plotItem.getAxis(self.plot_y.main_xaxis).setRange(*org_ver_range)
        self.util_panel.momentum_hor_value.setText('({:.4f})'.format(
            self.data_handler.axes[slit_ax][self.main_plot.pos[1].get_value()]))
        self.util_panel.momentum_vert_value.setText('({:.4f})'.format(
            self.data_handler.axes[scan_ax][self.main_plot.pos[0].get_value()]))

    def show_BZ_contour(self):
        if not self.util_panel.image_show_BZ.isChecked():
            return

        if (self.kx_axis is None) or (self.ky_axis is None):
            warning_box = QMessageBox()
            warning_box.setIcon(QMessageBox.Information)
            warning_box.setText('Data must be converted to k-space.')
            warning_box.setStandardButtons(QMessageBox.Ok)
            if warning_box.exec() == QMessageBox.Ok:
                self.util_panel.image_show_BZ.setChecked(False)
                return

        symmetry = self.util_panel.image_symmetry.value()
        if not ((symmetry == 4) or (symmetry == 6)):
            warning_box = QMessageBox()
            warning_box.setIcon(QMessageBox.Information)
            warning_box.setText('Only 4- and 6-fold symmetry supported.')
            warning_box.setStandardButtons(QMessageBox.Ok)
            if warning_box.exec() == QMessageBox.Ok:
                self.util_panel.image_show_BZ.setChecked(False)
                return

        a = self.util_panel.axes_conv_lc.value()
        if symmetry == 4:
            G = np.pi / a
            # b = 2 * G / np.sqrt(3)
            raw_pts = np.array([[-G, G], [G, G], [G, -G], [-G, -G]])
        elif symmetry == 6:
            G = np.pi / a
            b = 2 * G / np.sqrt(3)
            raw_pts = np.array([[-b / 2, -G], [b / 2, -G], [b, 0], [b / 2, G], [-b / 2, G], [-b, 0]])

        rotation_angle = self.util_panel.image_rotate_BZ.value()
        raw_pts = self.transform_points(raw_pts, rotation_angle)
        pts = self.find_index_coords(raw_pts)
        self.plot_between_points(pts)

    def plot_between_points(self, pts):
        for idx in range(len(pts) - 1):
            x = [pts[idx][0], pts[idx + 1][0]]
            y = [pts[idx][1], pts[idx + 1][1]]
            self.main_plot.plot(x, y)
        x = [pts[0][0], pts[-1][0]]
        y = [pts[0][1], pts[-1][1]]
        self.main_plot.plot(x, y)

    def show_orientation_info(self):

        title = 'piva -> beamline coordinates translator'
        self.info_box = ip.InfoWindow(self.util_panel.orient_info_window, title)
        self.info_box.show()

    def open_pit(self):
        """ Open the data in an instance of 
        :class:`data_slicer.pit.MainWindow`, which has the benefit of 
        providing a free-slicing ROI.
        """
        mw = pit.MainWindow()
        mw.data_handler.set_data(self.data_set.data, axes=self.data_handler.axes)
        mw.set_cmap(self.cmap_name)

    def open_2dviewer(self):
        data_set = deepcopy(self.data_set)
        cut_orient = self.util_panel.image_2dv_cut_selector.currentText()

        if cut_orient[0] == 'h':
            cut = self.data_handler.cut_x_data
            dim_value = self.data_set.yscale[self.main_plot.crosshair.hpos.get_value()]
            data_set.yscale = data_set.xscale
            idx = self.main_plot.crosshair.hpos.get_value()
            lbl = self.util_panel.momentum_hor_label.text()[:-1]
            if self.util_panel.bin_y.isChecked():
                n_bin = self.util_panel.bin_y_nbins.value()
                thread_idx = '{}: {} [{}]; nbin [{}]'.format(self.index, lbl, str(idx), str(n_bin))
            else:
                thread_idx = '{}: {} [{}]'.format(self.index, lbl, str(idx))
        else:
            cut = self.data_handler.cut_y_data.T
            dim_value = self.data_set.xscale[self.main_plot.crosshair.vpos.get_value()]
            idx = self.main_plot.crosshair.vpos.get_value()
            lbl = self.util_panel.momentum_vert_label.text()[:-1]
            if self.util_panel.bin_x.isChecked():
                n_bin = self.util_panel.bin_x_nbins.value()
                thread_idx = '{}: {} [{}]; nbin [{}]'.format(self.index, lbl, str(idx), str(n_bin))
            else:
                thread_idx = '{}: {} [{}]'.format(self.index, lbl, str(idx))

        data = np.ones((1, cut.shape[0], cut.shape[1]))
        data[0, :, :] = cut
        data_set.data = data
        data_set.xscale = np.array([1])
        data_set.scan_type = 'cut'

        # self.title = fname.split('/')[-1]
        # self.fname = fname

        if (data_set.scan_type == 'tilt scan') or (data_set.scan_type == 'DA scan'):
            data_set.tilt = dim_value
            thread_idx += '_@{:.3}deg'.format(dim_value)
        elif data_set.scan_type == 'hv scan':
            data_set.hv = dim_value
            thread_idx += '_@{:.1}eV'.format(dim_value)

        if thread_idx in self.db.data_viewers.keys():
            thread_running_box = QMessageBox()
            thread_running_box.setIcon(QMessageBox.Information)
            thread_running_box.setWindowTitle('Doh.')
            thread_running_box.setText('Same cut is already opened')
            thread_running_box.setStandardButtons(QMessageBox.Ok)
            if thread_running_box.exec() == QMessageBox.Ok:
                return

        try:
            self.db.data_viewers[thread_idx] = \
                p2d.MainWindow2D(self.db, data_set=data_set, index=thread_idx, slice=True)
        except Exception as e:
            raise e
            error_box = QMessageBox()
            error_box.setIcon(QMessageBox.Information)
            error_box.setText('Couldn\'t load data,  something went wrong.')
            error_box.setStandardButtons(QMessageBox.Ok)
            if error_box.exec() == QMessageBox.Ok:
                return
        finally:
            self.thread_count += 1

    @staticmethod
    def transform_points(pts, angle):
        theta = np.deg2rad(angle)
        transform_matrix = np.array([[np.cos(theta), -np.sin(theta)],
                                     [np.sin(theta), np.cos(theta)]])
        res_pts = []
        for pt in pts:
            res_pts.append(np.array(pt) @ transform_matrix)
        return res_pts

    def find_index_coords(self, raw_pts):

        x0, dx = self.kx_axis[0], wp.get_step(self.kx_axis)
        y0, dy = self.ky_axis[0], wp.get_step(self.ky_axis)
        res_pts = []

        for rp in raw_pts:
            if rp[0] > x0:
                x = int(np.abs((x0 - rp[0])) / dx)
            else:
                x = -int(np.abs((x0 - rp[0])) / dx)
            if rp[1] > y0:
                y = int(np.abs((y0 - rp[1])) / dy)
            else:
                y = -int(np.abs((y0 - rp[1])) / dy)
            res_pts.append([x, y])

        return res_pts

    def save_to_pickle(self):
        dataset = self.data_set
        savedir = self.fname[:-len(self.title)]
        up = self.util_panel
        file_selection = True
        # Prepare a filename with the .p suffix
        init_fname = '.'.join(self.title.split('.')[:-1] + ['p'])

        while file_selection:
            fname, fname_return_value = QtWidgets.QInputDialog.getText(self, '', 'File name:',
                                                                       QLineEdit.Normal, init_fname)
            if not fname_return_value:
                return

            # check if there is no fname colosions
            if fname in os.listdir(savedir):
                fname_colision_box = QMessageBox()
                fname_colision_box.setIcon(QMessageBox.Question)
                fname_colision_box.setWindowTitle('File name already used.')
                fname_colision_box.setText('File {} already exists.\nDo you want to overwrite it?'.format(fname))
                fname_colision_box.setStandardButtons(QMessageBox.Ok | QMessageBox.Cancel)
                if fname_colision_box.exec() == QMessageBox.Ok:
                    file_selection = False
                else:
                    init_fname = fname
            else:
                file_selection = False

        conditions = [up.axes_energy_Ef.value() != 0, up.axes_energy_hv.value() != 0, up.axes_energy_wf.value() != 0,
                      up.axes_gamma_y.value() != 0, up.axes_gamma_x.value() != 0]

        if np.any(conditions):
            save_cor_box = QMessageBox()
            save_cor_box.setIcon(QMessageBox.Question)
            save_cor_box.setWindowTitle('Save data')
            save_cor_box.setText("Do you want to save applied corrections?")
            save_cor_box.setStandardButtons(QMessageBox.No | QMessageBox.Ok | QMessageBox.Cancel)

            box_return_value = save_cor_box.exec()
            if box_return_value == QMessageBox.Ok:
                if up.axes_energy_Ef.value() != 0:
                    dataset.Ef = up.axes_energy_Ef.value()
                if up.axes_energy_hv.value() != 0:
                    dataset.hv = up.axes_energy_hv.value()
                if up.axes_energy_wf.value() != 0:
                    dataset.wf = up.axes_energy_wf.value()
                if not (self.kx_axis is None) and not (self.ky_axis is None):
                    dataset.kxscale = self.kx_axis
                    dataset.kyscale = self.ky_axis
            elif box_return_value == QMessageBox.No:
                pass
            elif box_return_value == QMessageBox.Cancel:
                return
        else:
            pass

        dl.dump(dataset, (savedir + fname), force=True)

    def load_saved_corrections(self, data_set):
        if type(data_set.Ef) == float:
            self.util_panel.axes_energy_Ef.setValue(data_set.Ef)
        if type(data_set.hv) == float:
            self.util_panel.axes_energy_hv.setValue(data_set.hv)
        if type(data_set.wf) == float:
            self.util_panel.axes_energy_wf.setValue(data_set.wf)
        if type(data_set.Ef) == float:
            self.util_panel.axes_energy_Ef.setValue(data_set.Ef)
        if hasattr(data_set, 'kxscale'):
            self.kx_axis = data_set.kxscale
        if hasattr(data_set, 'kyscale'):
            self.ky_axis = data_set.kyscale

    def load_saved_corrections_old(self, data_set):
        if hasattr(data_set, 'saved'):
            saved = data_set.saved
            if 'Ef' in saved.keys():
                self.util_panel.axes_energy_Ef.setValue(saved['Ef'])
            if 'hv' in saved.keys():
                self.util_panel.axes_energy_hv.setValue(saved['hv'])
            if 'wf' in saved.keys():
                self.util_panel.axes_energy_wf.setValue(saved['wf'])
            if 'gamma_x' in saved.keys():
                self.util_panel.axes_gamma_x.setValue(saved['gamma_x'])
                self.util_panel.orientate_init_x.setValue(saved['gamma_x'])
                self.util_panel.orientate_find_gamma_message.setText('Values loaded from file.')
            if 'gamma_y' in saved.keys():
                self.util_panel.axes_gamma_y.setValue(saved['gamma_y'])
                self.util_panel.orientate_init_y.setValue(saved['gamma_y'])
                self.util_panel.orientate_find_gamma_message.setText('Values loaded from file.')
            if 'kx' in saved.keys() and 'ky' in saved.keys():
                self.kx_axis = saved['kx']
                self.ky_axis = saved['ky']
                new_hor_range = [saved['kx'][0], saved['kx'][-1]]
                new_ver_range = [saved['ky'][0], saved['ky'][-1]]
                self.main_plot.plotItem.getAxis(self.main_plot.main_xaxis).setRange(*new_hor_range)
                self.main_plot.plotItem.getAxis(self.main_plot.main_yaxis).setRange(*new_ver_range)
                self.cut_x.plotItem.getAxis(self.cut_x.main_xaxis).setRange(*new_hor_range)
                self.cut_y.plotItem.getAxis(self.cut_y.main_xaxis).setRange(*new_ver_range)
                self.plot_x.plotItem.getAxis(self.plot_x.main_xaxis).setRange(*new_hor_range)
                self.plot_y.plotItem.getAxis(self.plot_y.main_xaxis).setRange(*new_ver_range)
                self.util_panel.momentum_hor_value.setText('({:.4f})'.format(
                    self.ky_axis[self.main_plot.pos[1].get_value()]))
                self.util_panel.momentum_vert_value.setText('({:.4f})'.format(
                    self.kx_axis[self.main_plot.pos[0].get_value()]))
        else:
            pass

        if not (data_set.Ef is None):
            self.util_panel.axes_energy_Ef.setValue(float(data_set.Ef))
        if not (data_set.hv is None):
            self.util_panel.axes_energy_hv.setValue(float(data_set.hv))
        if not (data_set.wf is None):
            self.util_panel.axes_energy_wf.setValue(float(data_set.wf))

