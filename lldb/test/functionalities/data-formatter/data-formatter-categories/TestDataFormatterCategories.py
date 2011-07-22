"""
Test lldb data formatter subsystem.
"""

import os, time
import unittest2
import lldb
from lldbtest import *

class DataFormatterTestCase(TestBase):

    mydir = os.path.join("functionalities", "data-formatter", "data-formatter-categories")

    @unittest2.skipUnless(sys.platform.startswith("darwin"), "requires Darwin")
    def test_with_dsym_and_run_command(self):
        """Test data formatter commands."""
        self.buildDsym()
        self.data_formatter_commands()

    def test_with_dwarf_and_run_command(self):
        """Test data formatter commands."""
        self.buildDwarf()
        self.data_formatter_commands()

    def setUp(self):
        # Call super's setUp().
        TestBase.setUp(self)
        # Find the line number to break at.
        self.line = line_number('main.cpp', '// Set break point at this line.')

    def data_formatter_commands(self):
        """Test that that file and class static variables display correctly."""
        self.runCmd("file a.out", CURRENT_EXECUTABLE_SET)

        self.expect("breakpoint set -f main.cpp -l %d" % self.line,
                    BREAKPOINT_CREATED,
            startstr = "Breakpoint created: 1: file ='main.cpp', line = %d, locations = 1" %
                        self.line)

        self.runCmd("run", RUN_SUCCEEDED)

        # The stop reason of the thread should be breakpoint.
        self.expect("thread list", STOPPED_DUE_TO_BREAKPOINT,
            substrs = ['stopped',
                       'stop reason = breakpoint'])

        # This is the function to remove the custom formats in order to have a
        # clean slate for the next test case (most of these categories do not
        # exist anymore, but we just make sure we delete all of them)
        def cleanup():
            self.runCmd('type format clear', check=False)
            self.runCmd('type summary clear', check=False)
            self.runCmd('type category delete Category1', check=False)
            self.runCmd('type category delete Category2', check=False)
            self.runCmd('type category delete NewCategory', check=False)
            self.runCmd("type category delete CircleCategory", check=False)
            self.runCmd("type category delete RectangleStarCategory", check=False)
            self.runCmd("type category delete BaseCategory", check=False)


        # Execute the cleanup function during test case tear down.
        self.addTearDownHook(cleanup)

        # Add a summary to a new category and check that it works
        self.runCmd("type summary add Rectangle -f \"ARectangle\" -w NewCategory")

        self.expect("frame variable r1 r2 r3", matching=False,
            substrs = ['r1 = ARectangle',
                       'r2 = ARectangle',
                       'r3 = ARectangle'])
        
        self.runCmd("type category enable NewCategory")

        self.expect("frame variable r1 r2 r3", matching=True,
                    substrs = ['r1 = ARectangle',
                               'r2 = ARectangle',
                               'r3 = ARectangle'])
        
        # Disable the category and check that the old stuff is there
        self.runCmd("type category disable NewCategory")

        self.expect("frame variable r1 r2 r3",
                    substrs = ['r1 = {',
                               'r2 = {',
                               'r3 = {'])

        # Re-enable the category and check that it works
        self.runCmd("type category enable NewCategory")

        self.expect("frame variable r1 r2 r3",
                    substrs = ['r1 = ARectangle',
                               'r2 = ARectangle',
                               'r3 = ARectangle'])

        # Delete the category and the old stuff should be there
        self.runCmd("type category delete NewCategory")

        self.expect("frame variable r1 r2 r3",
                    substrs = ['r1 = {',
                               'r2 = {',
                               'r3 = {'])

        # Add summaries to two different categories and check that we can switch
        self.runCmd("type summary add -f \"Width = ${var.w}, Height = ${var.h}\" Rectangle -w Category1")
        self.runCmd("type summary add -s \"return 'Area = ' + str( int(valobj.GetChildMemberWithName('w').GetValue()) * int(valobj.GetChildMemberWithName('h').GetValue()) );\" Rectangle -w Category2")

        # check that enable A B is the same as enable B enable A
        self.runCmd("type category enable Category1 Category2")
        
        self.expect("frame variable r1 r2 r3",
                    substrs = ['r1 = Width = ',
                               'r2 = Width = ',
                               'r3 = Width = '])

        self.runCmd("type category disable Category1")

        self.expect("frame variable r1 r2 r3",
                    substrs = ['r1 = Area = ',
                               'r2 = Area = ',
                               'r3 = Area = '])

        # switch again

        self.runCmd("type category enable Category1")

        self.expect("frame variable r1 r2 r3",
                    substrs = ['r1 = Width = ',
                               'r2 = Width = ',
                               'r3 = Width = '])

        # Re-enable the category and show that the preference is persisted
        self.runCmd("type category disable Category2")
        self.runCmd("type category enable Category2")
        
        self.expect("frame variable r1 r2 r3",
                    substrs = ['r1 = Area = ',
                               'r2 = Area = ',
                               'r3 = Area = '])

        # Now delete the favorite summary
        self.runCmd("type summary delete Rectangle -w Category2")

        self.expect("frame variable r1 r2 r3",
                    substrs = ['r1 = Width = ',
                               'r2 = Width = ',
                               'r3 = Width = '])

        # Delete the summary from the default category (that does not have it)
        self.runCmd("type summary delete Rectangle", check=False)

        self.expect("frame variable r1 r2 r3",
                    substrs = ['r1 = Width = ',
                               'r2 = Width = ',
                               'r3 = Width = '])

        # Now add another summary to another category and switch back and forth
        self.runCmd("type category delete Category1 Category2")

        self.runCmd("type summary add Rectangle -f \"Category1\" -w Category1")
        self.runCmd("type summary add Rectangle -f \"Category2\" -w Category2")

        self.runCmd("type category enable Category2")
        self.runCmd("type category enable Category1")
        
        self.expect("frame variable r1 r2 r3",
                substrs = ['r1 = Category1',
                           'r2 = Category1',
                           'r3 = Category1'])

        self.runCmd("type category disable Category1")

        self.expect("frame variable r1 r2 r3",
                    substrs = ['r1 = Category2',
                               'r2 = Category2',
                               'r3 = Category2'])

        # Check that re-enabling an enabled category works
        self.runCmd("type category enable Category1")

        self.expect("frame variable r1 r2 r3",
                    substrs = ['r1 = Category1',
                               'r2 = Category1',
                               'r3 = Category1'])

        self.runCmd("type category delete Category1")
        self.runCmd("type category delete Category2")

        self.expect("frame variable r1 r2 r3",
                    substrs = ['r1 = {',
                               'r2 = {',
                               'r3 = {'])

        # Check that multiple summaries can go into one category 
        self.runCmd("type summary add -f \"Width = ${var.w}, Height = ${var.h}\" Rectangle -w Category1")
        self.runCmd("type summary add -f \"Radius = ${var.r}\" Circle -w Category1")
        
        self.runCmd("type category enable Category1")

        self.expect("frame variable r1 r2 r3",
                    substrs = ['r1 = Width = ',
                               'r2 = Width = ',
                               'r3 = Width = '])

        self.expect("frame variable c1 c2 c3",
                    substrs = ['c1 = Radius = ',
                               'c2 = Radius = ',
                               'c3 = Radius = '])

        self.runCmd("type summary delete Circle -w Category1")
            
        self.expect("frame variable c1 c2 c3",
                    substrs = ['c1 = {',
                               'c2 = {',
                               'c3 = {'])

        # Add a regex based summary to a category
        self.runCmd("type summary add -f \"Radius = ${var.r}\" -x Circle -w Category1")

        self.expect("frame variable r1 r2 r3",
                    substrs = ['r1 = Width = ',
                               'r2 = Width = ',
                               'r3 = Width = '])

        self.expect("frame variable c1 c2 c3",
                    substrs = ['c1 = Radius = ',
                               'c2 = Radius = ',
                               'c3 = Radius = '])

        # Delete it
        self.runCmd("type summary delete Circle -w Category1")

        self.expect("frame variable c1 c2 c3",
                    substrs = ['c1 = {',
                               'c2 = {',
                               'c3 = {'])
        
        # Change a summary inside a category and check that the change is reflected
        self.runCmd("type summary add Circle -w Category1 -f \"summary1\"")

        self.expect("frame variable c1 c2 c3",
                    substrs = ['c1 = summary1',
                               'c2 = summary1',
                               'c3 = summary1'])

        self.runCmd("type summary add Circle -w Category1 -f \"summary2\"")
        
        self.expect("frame variable c1 c2 c3",
                    substrs = ['c1 = summary2',
                               'c2 = summary2',
                               'c3 = summary2'])

        # Check that our order of priority works. Start by clearing categories
        self.runCmd("type category delete Category1")

        self.runCmd("type summary add Shape -w BaseCategory -f \"AShape\"")
        self.runCmd("type category enable BaseCategory")

        self.expect("frame variable c1 r1 c_ptr r_ptr",
            substrs = ['AShape',
                       'AShape',
                       'AShape',
                       'AShape'])
    
        self.runCmd("type summary add Circle -w CircleCategory -f \"ACircle\"")
        self.runCmd("type summary add Rectangle -w RectangleCategory -f \"ARectangle\"")
        self.runCmd("type category enable CircleCategory")

        self.expect("frame variable c1 r1 c_ptr r_ptr",
                    substrs = ['ACircle',
                               'AShape',
                               'ACircle',
                               'AShape'])

        self.runCmd("type summary add \"Rectangle *\" -w RectangleStarCategory -f \"ARectangleStar\"")
        self.runCmd("type category enable RectangleStarCategory")

        self.expect("frame variable c1 r1 c_ptr r_ptr",
                substrs = ['ACircle',
                           'AShape',
                           'ACircle',
                           'ARectangleStar'])

        self.runCmd("type category enable RectangleCategory")

        self.expect("frame variable c1 r1 c_ptr r_ptr",
                    substrs = ['ACircle',
                               'ARectangle',
                               'ACircle',
                               'ARectangleStar'])

        # Check that abruptly deleting an enabled category does not crash us
        self.runCmd("type category delete RectangleCategory")

        self.expect("frame variable c1 r1 c_ptr r_ptr",
                    substrs = ['ACircle',
                               'AShape',
                               'ACircle',
                               'ARectangleStar'])
        
        # check that list commands work
        self.expect("type category list",
                substrs = ['RectangleStarCategory',
                           'is enabled'])

        self.expect("type summary list",
                substrs = ['ARectangleStar'])

        # Disable a category and check that it fallsback
        self.runCmd("type category disable CircleCategory")
        
        # check that list commands work
        self.expect("type category list",
                    substrs = ['CircleCategory',
                               'not enabled'])

        self.expect("frame variable c1 r1 c_ptr r_ptr",
                    substrs = ['AShape',
                               'AShape',
                               'AShape',
                               'ARectangleStar'])

        # check that synthetic children work into categories
        self.runCmd("type synth add Rectangle --child w --category RectangleCategory")
        self.runCmd("type category enable RectangleCategory")
        self.runCmd("type summary add Rectangle -f \" \" -e --category RectangleCategory")
        self.expect('frame variable r2',
            substrs = ['w = 9'])
        self.runCmd("type summary add Rectangle -f \" \" -e")
        self.expect('frame variable r2', matching=False,
                    substrs = ['h = 16'])

        # Now delete all categories
        self.runCmd("type category delete CircleCategory RectangleStarCategory BaseCategory RectangleCategory")

        # last of all, check that a deleted category with synth does not blow us up
        self.expect('frame variable r2',
                    substrs = ['w = 9',
                               'h = 16'])

if __name__ == '__main__':
    import atexit
    lldb.SBDebugger.Initialize()
    atexit.register(lambda: lldb.SBDebugger.Terminate())
    unittest2.main()
